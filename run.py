"""
Convenience launcher so the app can be started with a plain ``python run.py``
from the project root (equivalent to ``python -m quote_tracker.main``).
"""

from quote_tracker.main import main

if __name__ == "__main__":
    raise SystemExit(main())
