"""domain core

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "naming_config",
        sa.Column("magazine_folder_pattern", sa.String(length=255), nullable=False),
        sa.Column("year_folder_pattern", sa.String(length=255), nullable=False),
        sa.Column("issue_file_pattern", sa.String(length=255), nullable=False),
        sa.Column("replace_illegal_characters", sa.Boolean(), nullable=False),
        sa.Column("colon_replacement", sa.String(length=8), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_naming_config")),
    )
    op.create_table(
        "quality_profiles",
        sa.Column("name", sa.String(length=100), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_quality_profiles_name")),
    )
    op.create_table(
        "root_folders",
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_root_folders")),
        sa.UniqueConstraint("path", name=op.f("uq_root_folders_path")),
    )
    op.create_table(
        "magazines",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sort_title", sa.String(length=255), nullable=False),
        sa.Column("alternate_titles", sa.JSON(), nullable=False),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("first_issue_year", sa.Integer(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("quality_profile_id", sa.Integer(), nullable=False),
        sa.Column("root_folder_id", sa.Integer(), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("poster_url", sa.String(length=2048), nullable=True),
        sa.Column("issue_naming_template", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["quality_profile_id"],
            ["quality_profiles.id"],
            name=op.f("fk_magazines_quality_profile_id_quality_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["root_folder_id"],
            ["root_folders.id"],
            name=op.f("fk_magazines_root_folder_id_root_folders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_magazines")),
        sa.UniqueConstraint(
            "root_folder_id", "folder", name=op.f("uq_magazines_root_folder_id_folder")
        ),
    )
    with op.batch_alter_table("magazines", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_magazines_quality_profile_id"), ["quality_profile_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_magazines_root_folder_id"), ["root_folder_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_magazines_sort_title"), ["sort_title"], unique=False)
        batch_op.create_index(batch_op.f("ix_magazines_title"), ["title"], unique=False)

    op.create_table(
        "quality_profile_items",
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("max_size_mb", sa.Integer(), nullable=True),
        sa.Column("upgrade_until", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
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
            ["profile_id"],
            ["quality_profiles.id"],
            name=op.f("fk_quality_profile_items_profile_id_quality_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_profile_items")),
        sa.UniqueConstraint(
            "profile_id", "quality", name=op.f("uq_quality_profile_items_profile_id_quality")
        ),
    )
    with op.batch_alter_table("quality_profile_items", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_quality_profile_items_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "unmapped_files",
        sa.Column("root_folder_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
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
            ["root_folder_id"],
            ["root_folders.id"],
            name=op.f("fk_unmapped_files_root_folder_id_root_folders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_unmapped_files")),
    )
    with op.batch_alter_table("unmapped_files", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_unmapped_files_root_folder_id"), ["root_folder_id"], unique=False
        )

    op.create_table(
        "issues",
        sa.Column("magazine_id", sa.Integer(), nullable=False),
        sa.Column("issue_number", sa.String(length=100), nullable=False),
        sa.Column("sort_index", sa.Float(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("cover_url", sa.String(length=2048), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            ["magazine_id"],
            ["magazines.id"],
            name=op.f("fk_issues_magazine_id_magazines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issues")),
        sa.UniqueConstraint(
            "magazine_id", "issue_number", name=op.f("uq_issues_magazine_id_issue_number")
        ),
    )
    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.create_index(
            "ix_issues_magazine_id_sort_index", ["magazine_id", "sort_index"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_issues_publish_date"), ["publish_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_issues_status"), ["status"], unique=False)

    op.create_table(
        "files",
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("edition", sa.String(length=100), nullable=True),
        sa.Column("date_added", sa.DateTime(timezone=True), nullable=False),
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
            ["issue_id"], ["issues.id"], name=op.f("fk_files_issue_id_issues"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("issue_id", name=op.f("uq_files_issue_id")),
    )


def downgrade() -> None:
    op.drop_table("files")
    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_issues_status"))
        batch_op.drop_index(batch_op.f("ix_issues_publish_date"))
        batch_op.drop_index("ix_issues_magazine_id_sort_index")

    op.drop_table("issues")
    with op.batch_alter_table("unmapped_files", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_unmapped_files_root_folder_id"))

    op.drop_table("unmapped_files")
    with op.batch_alter_table("quality_profile_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quality_profile_items_profile_id"))

    op.drop_table("quality_profile_items")
    with op.batch_alter_table("magazines", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_magazines_title"))
        batch_op.drop_index(batch_op.f("ix_magazines_sort_title"))
        batch_op.drop_index(batch_op.f("ix_magazines_root_folder_id"))
        batch_op.drop_index(batch_op.f("ix_magazines_quality_profile_id"))

    op.drop_table("magazines")
    op.drop_table("root_folders")
    op.drop_table("quality_profiles")
    op.drop_table("naming_config")
