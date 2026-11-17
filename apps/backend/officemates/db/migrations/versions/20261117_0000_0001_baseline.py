"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-11-17

Empty on purpose: it establishes the ``alembic_version`` table so every later schema
change is a tracked revision. The first real tables arrive in Phase 1.
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
