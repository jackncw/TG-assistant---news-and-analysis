"""Delete archive folders older than the configured retention period.

Run: python scripts/cleanup.py
"""
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.json"
ARCHIVE = ROOT / "data" / "archive"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    keep_days = config["archive"]["keep_days"]
    cutoff = date.today() - timedelta(days=keep_days)

    if not ARCHIVE.exists():
        print("OK: no archive directory, nothing to do")
        return 0

    removed = 0
    for entry in sorted(ARCHIVE.iterdir()):
        if not entry.is_dir():
            continue
        try:
            folder_date = datetime.strptime(entry.name, "%Y-%m-%d").date()
        except ValueError:
            print(f"SKIP non-date folder: {entry.name}")
            continue
        if folder_date < cutoff:
            shutil.rmtree(entry)
            removed += 1
            print(f"Removed {entry.name}")

    print(f"OK: removed {removed} folder(s), cutoff {cutoff} (keep {keep_days} days)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
