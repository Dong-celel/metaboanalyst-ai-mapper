"""Compatibility shim for the former automation entry point.

New usage is ``python main.py run INPUT.csv``.
"""

from __future__ import annotations

import sys

from main import main


if __name__ == "__main__":
    print("Note: use `python main.py run INPUT.csv` for future runs.")
    raise SystemExit(main(["run", *sys.argv[1:]]))
