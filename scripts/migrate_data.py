#!/usr/bin/env python3
"""
Migrate user data from the old in-tree location to the new external home.

    Source:  ~/Desktop/imbuto/data/
    Target:  ~/.imbuto/data/

Preserves directory structure.  Skips files that already exist at the
destination to avoid accidental overwrites.  Prints a summary on exit.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


SRC = Path.home() / "Desktop" / "imbuto" / "data"
DST = Path.home() / ".imbuto" / "data"


def migrate() -> None:
    if not SRC.exists():
        print(f"[SKIP] Source directory does not exist: {SRC}")
        sys.exit(0)

    copied: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for src_file in sorted(SRC.rglob("*")):
        if not src_file.is_file():
            continue

        relative = src_file.relative_to(SRC)
        dst_file = DST / relative

        if dst_file.exists():
            skipped.append(str(relative))
            continue

        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied.append(str(relative))
        except Exception as exc:
            errors.append(f"{relative}: {exc}")

    # ── Summary ──────────────────────────────────────────────────────
    print("\n══════════════════════════════════════════════")
    print("  IMBUTO Data Migration Summary")
    print("══════════════════════════════════════════════")
    print(f"  Source : {SRC}")
    print(f"  Target : {DST}")
    print(f"  Copied : {len(copied)}")
    print(f"  Skipped: {len(skipped)} (already exist)")
    print(f"  Errors : {len(errors)}")
    print("──────────────────────────────────────────────")

    if copied:
        print("\n  Copied files:")
        for f in copied:
            print(f"    + {f}")

    if skipped:
        print("\n  Skipped files:")
        for f in skipped:
            print(f"    ~ {f}")

    if errors:
        print("\n  Errors:")
        for e in errors:
            print(f"    ! {e}")

    print()


if __name__ == "__main__":
    migrate()
