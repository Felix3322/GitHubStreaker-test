#!/usr/bin/env python3
import datetime as dt
import json
import os
import random
import string
import subprocess
from pathlib import Path
from typing import Optional


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

    pattern = data.get("pattern") or []
    if len(pattern) < 7:
        print("pattern.json:pattern 结构非法。")
        return 1

    today = dt.datetime.utcnow().date()
    delta = (today - start_date).days
    if delta < 0:
        print("图案尚未开始。")
        return 0

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

    identity = os.environ.get("GITHUB_ACTOR") or os.environ.get("COMMITTER_NAME")
    commits_today = _count_commits_today(repo_root, identity)
    if commits_today is None:
        return 1
    if commits_today > need:
        print(f"今日已有 {commits_today} 次提交，超过目标 {need}。请检查图案或等待明日。")
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


if __name__ == "__main__":
    raise SystemExit(main())
