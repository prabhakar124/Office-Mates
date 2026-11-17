"""identity and audit: tenants, users, memberships, audit_logs

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17

MySQL commits each DDL statement on its own, so ``downgrade`` drops in reverse order and
every step uses names that exist only after the matching ``upgrade`` step.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from officemates.db.types import UTCDateTime, UUIDBinary

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_MESSAGE = "audit_logs is append-only"


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUIDBinary(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("pinecone_namespace", sa.String(64), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.UniqueConstraint("pinecone_namespace", name="uq_tenants_pinecone_namespace"),
        sa.CheckConstraint("`status` IN ('active', 'suspended')", name="ck_tenants_status"),
        sa.CheckConstraint("`plan` IN ('standard')", name="ck_tenants_plan"),
    )

    op.create_table(
        "users",
        sa.Column("id", UUIDBinary(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("email_verified_at", UTCDateTime(), nullable=True),
        sa.Column("last_login_at", UTCDateTime(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("`status` IN ('active', 'invited', 'disabled')", name="ck_users_status"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", UUIDBinary(), nullable=False),
        sa.Column("tenant_id", UUIDBinary(), nullable=False),
        sa.Column("user_id", UUIDBinary(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id_user_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_memberships_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "`role` IN ('owner', 'admin', 'editor', 'member', 'viewer')",
            name="ck_memberships_role",
        ),
        sa.CheckConstraint("`status` IN ('active', 'removed')", name="ck_memberships_status"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", UUIDBinary(), nullable=False),
        sa.Column("tenant_id", UUIDBinary(), nullable=False),
        sa.Column("actor_user_id", UUIDBinary(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", UUIDBinary(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_audit_logs_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_logs_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_logs_actor_user_id_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_audit_logs_tenant_id_created_at", "audit_logs", ["tenant_id", "created_at"])
    op.create_index("ix_audit_logs_tenant_id_action", "audit_logs", ["tenant_id", "action"])

    # Append-only, enforced by the database. The triggers fire for every account; only an
    # account allowed to drop triggers (the migrator, never the app) could get around
    # them, so retention purges and tenant deletion must run as a migrator-account job.
    # The users.id ON DELETE SET NULL cascade still works: MySQL does not fire triggers
    # for foreign-key cascades.
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_audit_logs_no_{event.lower()} BEFORE {event} ON audit_logs "
            f"FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '{APPEND_ONLY_MESSAGE}'"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update")
    op.drop_table("audit_logs")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("tenants")
