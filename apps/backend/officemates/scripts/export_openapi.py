"""Write the API's OpenAPI schema to a file (or stdout) without starting a server.

Used by the frontend to generate its typed API client:
    uv run python -m officemates.scripts.export_openapi ../web/lib/api/openapi.json
"""

import json
import sys
from pathlib import Path

from officemates.core.config import Environment, Settings
from officemates.main import create_app


def main(argv: list[str]) -> int:
    # Docs are forced on so the schema is generated regardless of the local environment.
    app = create_app(
        Settings(_env_file=None, environment=Environment.LOCAL, docs_enabled=True, log_json=True)
    )
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if len(argv) > 1:
        Path(argv[1]).write_text(schema, encoding="utf-8")
    else:
        sys.stdout.write(schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
