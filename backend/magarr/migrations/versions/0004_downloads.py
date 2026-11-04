"""Downloads: clients, tracked downloads, history, blocklist; profile decision rules.

Existing quality profiles get server defaults (both protocols, no term rules) so they upgrade.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_clients",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("implementation", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_clients")),
        sa.UniqueConstraint("name", name=op.f("uq_download_clients_name")),
    )
    op.create_table(
        "download_settings",
        sa.Column("redownload_failed", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_settings")),
    )
    op.create_table(
        "blocklist",
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("magazine_id", sa.Integer(), nullable=True),
        sa.Column("guid", sa.String(length=1024), nullable=False),
        sa.Column("indexer_id", sa.Integer(), nullable=True),
        sa.Column("source_title", sa.String(length=1024), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_blocklist_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["magazine_id"],
            ["magazines.id"],
            name=op.f("fk_blocklist_magazine_id_magazines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blocklist")),
    )
    with op.batch_alter_table("blocklist", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_blocklist_issue_id"), ["issue_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_blocklist_magazine_id"), ["magazine_id"], unique=False)

    op.create_table(
        "downloads",
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("download_client_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("release", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("size_left", sa.BigInteger(), nullable=False),
        sa.Column("output_path", sa.String(length=2048), nullable=True),
        sa.Column("message", sa.String(length=1024), nullable=True),
        sa.Column("missing_polls", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["download_client_id"],
            ["download_clients.id"],
            name=op.f("fk_downloads_download_client_id_download_clients"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_downloads_issue_id_issues"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_downloads")),
    )
    with op.batch_alter_table("downloads", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_downloads_download_client_id"), ["download_client_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_downloads_issue_id"), ["issue_id"], unique=False)
        batch_op.create_index("ix_downloads_status", ["status"], unique=False)

    op.create_table(
        "history",
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("magazine_id", sa.Integer(), nullable=True),
        sa.Column("download_id", sa.Integer(), nullable=True),
        sa.Column("source_title", sa.String(length=1024), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_history_issue_id_issues"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["magazine_id"],
            ["magazines.id"],
            name=op.f("fk_history_magazine_id_magazines"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_history")),
    )
    with op.batch_alter_table("history", schema=None) as batch_op:
        batch_op.create_index("ix_history_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_history_event_type"), ["event_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_history_issue_id"), ["issue_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_history_magazine_id"), ["magazine_id"], unique=False)

    with op.batch_alter_table("quality_profiles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "protocols",
                sa.JSON(),
                nullable=False,
                server_default=sa.text('\'["usenet", "torrent"]\''),
            )
        )
        batch_op.add_column(
            sa.Column("must_contain", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(
            sa.Column("must_not_contain", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("quality_profiles", schema=None) as batch_op:
        batch_op.drop_column("must_not_contain")
        batch_op.drop_column("must_contain")
        batch_op.drop_column("protocols")

    with op.batch_alter_table("history", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_history_magazine_id"))
        batch_op.drop_index(batch_op.f("ix_history_issue_id"))
        batch_op.drop_index(batch_op.f("ix_history_event_type"))
        batch_op.drop_index("ix_history_created_at")

    op.drop_table("history")
    with op.batch_alter_table("downloads", schema=None) as batch_op:
        batch_op.drop_index("ix_downloads_status")
        batch_op.drop_index(batch_op.f("ix_downloads_issue_id"))
        batch_op.drop_index(batch_op.f("ix_downloads_download_client_id"))

    op.drop_table("downloads")
    with op.batch_alter_table("blocklist", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_blocklist_magazine_id"))
        batch_op.drop_index(batch_op.f("ix_blocklist_issue_id"))

    op.drop_table("blocklist")
    op.drop_table("download_settings")
    op.drop_table("download_clients")
