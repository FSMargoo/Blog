#!/usr/bin/env python3
"""
Deploy the built blog to GitHub Pages.

Clones (or updates) the Pages repository, copies the public/ output into it,
preserves CNAME, commits, and pushes.

Usage:
    python deploy.py              # build + deploy
    python deploy.py --no-build   # deploy without rebuilding
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
PUBLIC = ROOT / "public"
PAGES_REPO = "https://github.com/FSMargoo/fsmargoo.github.io.git"
PAGES_DIR = ROOT / "fsmargoo.github.io"

KEEP_FILES = {".git", "CNAME"}


def run(cmd, cwd=None):
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


def build():
    print("[1/3] Building blog...")
    run("python build.py", cwd=ROOT)


def clone_or_pull():
    if PAGES_DIR.exists():
        print("[2/3] Pulling latest from Pages repo...")
        run("git pull origin main", cwd=PAGES_DIR)
    else:
        print("[2/3] Cloning Pages repo...")
        run(f'git clone {PAGES_REPO} "{PAGES_DIR}"')


def sync():
    print("[3/3] Syncing public/ to Pages repo...")

    # Remove everything except .git and CNAME
    for item in PAGES_DIR.iterdir():
        if item.name in KEEP_FILES:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    # Copy public contents
    for item in PUBLIC.iterdir():
        dst = PAGES_DIR / item.name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)

    # Commit and push
    run("git add -A", cwd=PAGES_DIR)
    run('git commit -m "Deploy"', cwd=PAGES_DIR)
    run("git push origin main", cwd=PAGES_DIR)

    print("\nDeployed to https://fsmargoo.github.io")


def main():
    parser = argparse.ArgumentParser(description="Deploy blog to GitHub Pages")
    parser.add_argument("--no-build", action="store_true", help="Skip build step")
    args = parser.parse_args()

    if not args.no_build:
        build()
    clone_or_pull()
    sync()


if __name__ == "__main__":
    main()
