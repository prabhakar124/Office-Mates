"""refresh_tokens

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from officemates.db.types import UTCDateTime, UUIDBinary

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUIDBinary(), nullable=False),
        sa.Column("user_id", UUIDBinary(), nullable=False),
        sa.Column("session_tenant_id", UUIDBinary(), nullable=False),
        sa.Column("family_id", UUIDBinary(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.Column("revoke_reason", sa.String(32), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_tenant_id"],
            ["tenants.id"],
            name="fk_refresh_tokens_session_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "`revoke_reason` IS NULL OR `revoke_reason` IN ('rotated', 'logout', 'reuse_detected')",
            name="ck_refresh_tokens_revoke_reason",
        ),
    )
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
