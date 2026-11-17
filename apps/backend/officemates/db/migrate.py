"""Alembic entry point that needs no alembic.ini, so it works the same from a source
checkout and from the installed package inside the Docker image.

    python -m officemates.db.migrate upgrade head
    python -m officemates.db.migrate revision --autogenerate -m "add tenants"
    python -m officemates.db.migrate current

Migrations run as the ``migrator`` MySQL account (``OM_DATABASE_MIGRATION_URL``); the
application's own account cannot change the schema.
"""

import sys
from pathlib import Path

from alembic.config import CommandLine, Config

from officemates.core.config import Settings, get_settings
from officemates.core.logging import configure_logging

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def make_config(database_url: str | None = None, settings: Settings | None = None) -> Config:
    if database_url is None:
        settings = settings or get_settings()
        if settings.database_migration_url is None:
            raise SystemExit("OM_DATABASE_MIGRATION_URL is not set")
        database_url = settings.database_migration_url.get_secret_value()

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option(
        "file_template",
        "%%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(rev)s_%%(slug)s",
    )
    cfg.set_main_option("timezone", "UTC")
    # Kept out of the main options so the password is never echoed by Alembic.
    cfg.attributes["database_url"] = database_url
    return cfg


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)  # shows Alembic's progress
    cli = CommandLine(prog="python -m officemates.db.migrate")
    options = cli.parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not hasattr(options, "cmd"):
        cli.parser.error("too few arguments")
    cli.run_cmd(make_config(), options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
