"""indexes for the backlog and Wanted orders

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_issues_status_last_searched_at", "issues", ["status", "last_searched_at"])
    op.create_index("ix_issues_status_publish_date", "issues", ["status", "publish_date"])
    # Both start with status, so the single-column index only gets in the planner's way.
    op.drop_index("ix_issues_status", table_name="issues")


def downgrade() -> None:
    op.create_index("ix_issues_status", "issues", ["status"])
    op.drop_index("ix_issues_status_publish_date", table_name="issues")
    op.drop_index("ix_issues_status_last_searched_at", table_name="issues")
