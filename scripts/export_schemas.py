"""Write JSON Schema for every AgentRadar contract model.

Run from the repo root: `python scripts/export_schemas.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "contracts" / "schemas"
sys.path.insert(0, str(ROOT))

from src.main.agentradar.contracts.collector import (  # noqa: E402
    CollectorRun,
    CollectorSpec,
    HealthVerdict,
)
from src.main.agentradar.contracts.dependency import (  # noqa: E402
    Dependency,
    ReleaseEvent,
    Watchlist,
)
from src.main.agentradar.contracts.evidence import (  # noqa: E402
    TestCase,
    TestReport,
    TestSelection,
)
from src.main.agentradar.contracts.impact import (  # noqa: E402
    BlastRadius,
    ContactPoint,
    ImpactRow,
)
from src.main.agentradar.contracts.mission import ActionPlan, Mission  # noqa: E402
from src.main.agentradar.contracts.patch import Patch, VerifyResult  # noqa: E402

MODELS = (
    Dependency,
    Watchlist,
    ReleaseEvent,
    ContactPoint,
    BlastRadius,
    ImpactRow,
    TestSelection,
    TestCase,
    TestReport,
    Patch,
    VerifyResult,
    CollectorSpec,
    HealthVerdict,
    CollectorRun,
    Mission,
    ActionPlan,
)


def main() -> int:
    """Emit one JSON Schema file per contract model into contracts/schemas/.

    Pass `--check` to fail if committed schemas drift from the models.
    """
    check = "--check" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    drifted: list[str] = []
    for model in MODELS:
        path = OUT / f"{model.__name__}.json"
        rendered = json.dumps(model.model_json_schema(), indent=2) + "\n"
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                drifted.append(path.relative_to(ROOT).as_posix())
            continue
        path.write_text(rendered, encoding="utf-8")
        print(path.relative_to(ROOT).as_posix())
    if check:
        if drifted:
            print("schema drift:", file=sys.stderr)
            print("\n".join(drifted), file=sys.stderr)
            print("Run `python scripts/export_schemas.py` and commit.", file=sys.stderr)
            return 1
        print("OK: schemas match models")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
