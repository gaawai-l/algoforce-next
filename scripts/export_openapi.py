"""Generate the frontend contract from the actual application schema."""

import json
from pathlib import Path

from wheelhouse.api import app

Path("frontend/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
