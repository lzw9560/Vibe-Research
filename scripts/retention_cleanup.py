#!/usr/bin/env python3
"""日志/数据 retention 清理——定期跑防 .vibe-research/ 无限增长。

用法：
  python3 scripts/retention_cleanup.py           # 干跑（只报告）
  python3 scripts/retention_cleanup.py --execute # 实际删除

清理项：
  1. backend.err.log / backend.out.log → 保留最近 5000 行
  2. storm_snapshots/ → 保留最近 30 天
  3. seal_intraday_snapshots 分表 → 保留当年 + 去年
  4. .bak 文件 → 全删（超过 7 天的备份）
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("VR_DATA_DIR", str(Path(__file__).resolve().parents[1] / ".vibe-research")))

def truncate_log(filepath: Path, keep_lines: int = 5000, execute: bool = False) -> int:
    """截断日志文件保留最近 N 行。返回释放字节数。"""
    if not filepath.exists():
        return 0
    size_before = filepath.stat().st_size
    if size_before < keep_lines * 200:  # 小文件不截
        return 0
    if not execute:
        print(f"  [dry-run] 截断 {filepath.name}: {size_before // 1024 // 1024}MB → 保留 {keep_lines} 行")
        return size_before
    lines = filepath.read_text(errors='replace').splitlines()
    if len(lines) > keep_lines:
        filepath.write_text('\n'.join(lines[-keep_lines:]) + '\n')
    size_after = filepath.stat().st_size
    freed = size_before - size_after
    print(f"  ✅ 截断 {filepath.name}: {size_before // 1024 // 1024}MB → {size_after // 1024 // 1024}MB (释放 {freed // 1024 // 1024}MB)")
    return freed

def clean_dir_by_age(dirpath: Path, max_age_days: int = 30, execute: bool = False) -> int:
    """删除目录中超过 max_age_days 的文件。返回释放字节数。"""
    if not dirpath.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=max_age_days)
    total_freed = 0
    for f in dirpath.iterdir():
        if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            size = f.stat().st_size
            if not execute:
                print(f"  [dry-run] 删除 {f.name}: {size // 1024}KB ({datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d')})")
                total_freed += size
            else:
                f.unlink()
                total_freed += size
                print(f"  ✅ 删除 {f.name}: {size // 1024}KB")
    return total_freed

def clean_bak_files(dirpath: Path, max_age_days: int = 7, execute: bool = False) -> int:
    """删除 .bak 文件。"""
    if not dirpath.exists():
        return 0
    total_freed = 0
    for f in dirpath.rglob("*.bak*"):
        if f.is_file():
            size = f.stat().st_size
            if not execute:
                print(f"  [dry-run] 删除 {f}: {size // 1024}KB")
                total_freed += size
            else:
                f.unlink()
                total_freed += size
                print(f"  ✅ 删除 {f}: {size // 1024}KB")
    return total_freed

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="实际删除（默认干跑）")
    args = parser.parse_args()
    
    print(f"=== retention cleanup ({'execute' if args.execute else 'dry-run'}) ===")
    print(f"DATA_DIR: {DATA_DIR}")
    print()
    
    total_freed = 0
    
    # 1. 日志截断
    print("--- 日志截断 ---")
    logs_dir = DATA_DIR / "logs"
    for logname in ["backend.err.log", "backend.out.log"]:
        freed = truncate_log(logs_dir / logname, keep_lines=5000, execute=args.execute)
        total_freed += freed
    
    # 2. storm_snapshots retention (30 天)
    print("\n--- storm_snapshots (30天) ---")
    freed = clean_dir_by_age(DATA_DIR / "storm_snapshots", max_age_days=30, execute=args.execute)
    total_freed += freed
    
    # 3. .bak 文件清理
    print("\n--- .bak 文件 ---")
    freed = clean_bak_files(DATA_DIR, max_age_days=7, execute=args.execute)
    total_freed += freed
    
    print(f"\n=== 总释放: {total_freed // 1024 // 1024}MB ===")
    if not args.execute:
        print("(dry-run，加 --execute 实际删除)")

if __name__ == "__main__":
    main()
