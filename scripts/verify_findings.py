"""Verify a code reviewer's findings against our own indexed pipeline.

    python scripts/verify_findings.py --pr 20
    python scripts/verify_findings.py --pr 20 --no-run     # locate only, instant
    python scripts/verify_findings.py --pr 20 --fix        # attempt proven repairs

The implementation lives in `agentradar.cli.verify_findings`. This file is the
command people type; keeping the logic in the package is what lets tests reach
it through a real import, and therefore what lets the graph see it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main.agentradar.cli.verify_findings import main

if __name__ == "__main__":
    raise SystemExit(main())
