"""Default to no year folders: issues go directly in the magazine folder.

Installs still using the old default year folder pattern ("Season {year}") switch to blank;
a pattern the user chose themselves is left alone.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DEFAULT = "Season {year}"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE naming_config SET year_folder_pattern = '' WHERE year_folder_pattern = :old"
        ).bindparams(old=OLD_DEFAULT)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE naming_config SET year_folder_pattern = :old WHERE year_folder_pattern = ''"
        ).bindparams(old=OLD_DEFAULT)
    )
