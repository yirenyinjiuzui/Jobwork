"""Friendly entry point; no data is opened before the preflight passes."""
from pathlib import Path
import sys

REQUIRED = ("server.py", "workbench.py", "discovery.py", "tracker.py", "calendar_export.py", "location_review.py", "assessment_tasks.py",
            "web/index.html", "web/app.js", "web/style.css", "extension/demo-form.html",
            "extension/demo-form.css")

def preflight(root, version=None):
    version = sys.version_info if version is None else version
    if tuple(version[:2]) < (3, 11):
        return ["Python 3.11 or newer is required. Install it from python.org."]
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    return ["Incomplete extraction: " + ", ".join(missing) +
            ". Extract the entire ZIP into a NEW folder; do not run inside the ZIP."] if missing else []

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--data-tools':
        from data_snapshot import main as data_main
        return data_main(sys.argv[2:])
    errors = preflight(Path(__file__).resolve().parent)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    try:
        from server import run
        return run()
    except (OSError, ImportError) as exc:
        print("Cannot start: %s. Check Python installation and folder permissions. "
              "Keep your existing data folder; do not delete it." % exc, file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
