#!/usr/bin/env python3
"""One-time move of legacy uploads from app/static/uploads into VTT_DATA_DIR.

Legacy uploads lived inside the application tree (which is replaced on every
container rebuild). They now live under VTT_DATA_DIR/uploads and keep the same
public URL (/uploads/<file>), so database rows never change.

Idempotent: existing destination files are never overwritten; leftovers stay
behind for manual inspection. Run it once after upgrading:

    python scripts/move_uploads.py
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import db  # noqa: E402  (reads VTT_DATA_DIR at import)

OLD = os.path.join(ROOT, "app", "static", "uploads")
NEW = os.path.join(db.DATA_DIR, "uploads")


def main():
    if not os.path.isdir(OLD):
        print("nothing to migrate (no legacy directory)")
        return
    os.makedirs(NEW, exist_ok=True)
    moved = skipped = 0
    for fname in sorted(os.listdir(OLD)):
        src = os.path.join(OLD, fname)
        if not os.path.isfile(src) or fname == ".gitkeep":
            continue
        dst = os.path.join(NEW, fname)
        if os.path.exists(dst):
            print(f"skip (already exists): {fname}")
            skipped += 1
            continue
        shutil.move(src, dst)
        print(f"moved: {fname}")
        moved += 1
    print(f"done: {moved} moved, {skipped} skipped -> {NEW}")


if __name__ == "__main__":
    main()
