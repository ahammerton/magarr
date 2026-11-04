"""import

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_settings",
        sa.Column("auto_import", sa.Boolean(), nullable=False),
        sa.Column("usenet_import_mode", sa.String(length=16), nullable=False),
        sa.Column("torrent_import_mode", sa.String(length=16), nullable=False),
        sa.Column("remove_completed_downloads", sa.Boolean(), nullable=False),
        sa.Column("recycle_bin", sa.String(length=1024), nullable=False),
        sa.Column("file_chmod", sa.String(length=4), nullable=False),
        sa.Column("folder_chmod", sa.String(length=4), nullable=False),
        sa.Column("chown_user", sa.Integer(), nullable=True),
        sa.Column("chown_group", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_settings")),
    )
    op.create_table(
        "remote_path_mappings",
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("remote_path", sa.String(length=1024), nullable=False),
        sa.Column("local_path", sa.String(length=1024), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_remote_path_mappings")),
        sa.UniqueConstraint(
            "host", "remote_path", name=op.f("uq_remote_path_mappings_host_remote_path")
        ),
    )


def downgrade() -> None:
    op.drop_table("remote_path_mappings")
    op.drop_table("media_settings")
