"""automation: RSS sync, backlog search, expected issues, retries, search cutoff

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_settings",
        sa.Column("monitoring_enabled", sa.Boolean(), nullable=False),
        sa.Column("rss_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("backlog_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("backlog_batch_size", sa.Integer(), nullable=False),
        sa.Column("expected_lookahead_days", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_settings")),
    )
    with op.batch_alter_table("download_settings") as batch:
        batch.add_column(sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"))
    with op.batch_alter_table("issues") as batch:
        batch.add_column(sa.Column("last_searched_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("magazines") as batch:
        batch.add_column(sa.Column("search_cutoff", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("magazines") as batch:
        batch.drop_column("search_cutoff")
    with op.batch_alter_table("issues") as batch:
        batch.drop_column("last_searched_at")
    with op.batch_alter_table("download_settings") as batch:
        batch.drop_column("max_retries")
    op.drop_table("automation_settings")
