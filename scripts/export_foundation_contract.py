"""Export the actual foundation contract for TypeScript generation."""

import json
from pathlib import Path

from wheelhouse_service.http import create_app

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "integrations/wealthfolio/openapi.json").write_text(
    json.dumps(create_app().openapi(), indent=2) + "\n"
)
