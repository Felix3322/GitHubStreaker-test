#!/usr/bin/env python3
import datetime as dt
import json
import os
import random
import string
import subprocess
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    pattern_path = repo_root / "pattern.json"
    if not pattern_path.exists():
        print("pattern.json 不存在，无法继续。")
        return 1

    data = json.loads(pattern_path.read_text(encoding="utf-8"))
    try:
        start_date = dt.date.fromisoformat(data["start_date"])
    except Exception:
        print("pattern.json:start_date 无效。")
        return 1

    mode = (data.get("mode") or "pattern").lower()
    if mode not in ("pattern", "daily"):
        mode = "pattern"
    pattern = data.get("pattern") or []
    daily_goal = int(data.get("daily_commit_count") or 0)

    today = dt.datetime.utcnow().date()
    delta = (today - start_date).days
    if delta < 0:
        print("图案尚未开始。")
        return 0

    need = 0
    if mode == "daily":
        need = max(0, daily_goal)
        if need <= 0:
            print("每日定量模式未配置 daily_commit_count。")
            return 1
    else:
        if len(pattern) < 7:
            print("pattern.json:pattern 结构非法。")
            return 1
        first_row = pattern[0]
        if any(len(row) != len(first_row) for row in pattern[:7]):
            print("pattern.json:pattern 列长度不一致。")
            return 1
        cols = len(first_row)
        if cols == 0:
            print("图案宽度为 0。")
            return 0
        idx = delta
        col = idx // 7
        row = idx % 7
        if col >= cols:
            print("图案已经完成。")
            return 0
        try:
            need = int(pattern[row][col])
        except (ValueError, TypeError):
            need = 0

    actor = os.environ.get("GITHUB_ACTOR") or (data.get("github_username") or "").strip()
    identity = actor or os.environ.get("COMMITTER_NAME")
    commits_today = _count_commits_today(repo_root, identity)
    if commits_today is None:
        return 1
    if commits_today > need:
        message = f"今日已有 {commits_today} 次提交，超过目标 {need}。请检查图案或等待明日。"
        print(message)
        _create_issue(repo_root, message, actor)
        return 1

    if need <= 0:
        print("今日像素=0，不提交。")
        return 0

    if commits_today == need:
        print("今日提交数已满足目标，跳过。")
        return 0

    data_dir = os.environ.get("DATA_DIR") or "heatmap"
    out_dir = repo_root / data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{today.isoformat()}.txt"
    existing = 0
    if out_file.exists():
        with out_file.open("r", encoding="utf-8") as handle:
            existing = sum(1 for _ in handle)

    if existing > need:
        print("heatmap 文件中的记录数已超过目标，请手动修正后重试。")
        return 1
    if existing == need:
        print("已达成目标提交数。")
        return 0

    to_write = need - existing
    with out_file.open("a", encoding="utf-8") as handle:
        for idx in range(existing + 1, existing + to_write + 1):
            stamp = dt.datetime.utcnow().isoformat()
            payload = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            handle.write(f"{stamp} #{idx}/{need} {payload}\n")

    try:
        subprocess.run(["git", "add", str(out_file)], check=True, cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        print(f"git add 失败：{exc}")
        return 1

    print(f"已写入 {to_write} 行，等待 workflow 统一提交。")
    return 0


def _count_commits_today(repo_root: Path, identity: Optional[str]):
    today = dt.datetime.utcnow().date()
    since = dt.datetime.combine(today, dt.time.min).isoformat() + "Z"
    cmd = ["git", "log", f"--since={since}", "--pretty=%H"]
    if identity:
        cmd.append(f"--author={identity}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root, check=False)
    except FileNotFoundError:
        print("未找到 git 命令，无法检测今日提交。")
        return None
    if proc.returncode != 0:
        msg = proc.stderr.strip() or f"git log exit code {proc.returncode}"
        print(f"检查今日提交失败：{msg}")
        return None
    count = sum(1 for line in proc.stdout.splitlines() if line.strip())
    return count


def _create_issue(repo_root: Path, message: str, actor: Optional[str]) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("缺少 GITHUB_TOKEN，无法创建提醒 issue。")
        return

    slug = _detect_repo_slug(repo_root)
    if not slug:
        print("无法解析仓库地址，跳过 issue 创建。")
        return

    mention = f"@{actor}" if actor else ""
    body = f"{message}\n\n{mention}".strip()
    title = f"Heatmap Painter quota exceeded {dt.datetime.utcnow().date().isoformat()}"

    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/issues",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "heatmap-painter-bot",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            if 200 <= resp.status < 300:
                print("已创建提醒 issue，等待用户处理。")
            else:
                print(f"创建 issue 失败，HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="ignore")
        print(f"创建 issue 失败：{exc.code} {error_text}")
    except Exception as exc:
        print(f"创建 issue 出错：{exc}")


def _detect_repo_slug(repo_root: Path) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=False,
        )
    except Exception:
        return None
    url = (proc.stdout or "").strip()
    if not url:
        return None
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@"):
        try:
            _, path = url.split(":", 1)
            return path
        except ValueError:
            return None
    if "github.com/" in url:
        return url.split("github.com/")[-1]
    return None


if __name__ == "__main__":
    raise SystemExit(main())
