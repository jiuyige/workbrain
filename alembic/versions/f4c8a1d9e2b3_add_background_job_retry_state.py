"""add background job retry state

Revision ID: f4c8a1d9e2b3
Revises: d7a3f9c2b8e1
Create Date: 2026-07-20 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4c8a1d9e2b3"
down_revision: Union[str, Sequence[str], None] = "d7a3f9c2b8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "backgroundjob",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "backgroundjob",
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
    )
    op.alter_column(
        "backgroundjob",
        "attempt_count",
        existing_type=sa.Integer(),
        server_default=None,
    )
    op.create_check_constraint(
        "ck_backgroundjob_attempt_count_nonnegative",
        "backgroundjob",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_backgroundjob_retry_state",
        "backgroundjob",
        """
        (status = 'queued' OR next_retry_at IS NULL)
        AND (next_retry_at IS NULL OR next_retry_at >= created_at)
        """,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_backgroundjob_retry_state",
        "backgroundjob",
        type_="check",
    )
    op.drop_constraint(
        "ck_backgroundjob_attempt_count_nonnegative",
        "backgroundjob",
        type_="check",
    )
    op.drop_column("backgroundjob", "next_retry_at")
    op.drop_column("backgroundjob", "attempt_count")
