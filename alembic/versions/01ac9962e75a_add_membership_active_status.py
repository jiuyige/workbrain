"""add membership active status

Revision ID: 01ac9962e75a
Revises: 2fea325162fc
Create Date: 2026-07-18 15:31:31.562580

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "01ac9962e75a"
down_revision: Union[str, Sequence[str], None] = "2fea325162fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "membership",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "membership",
        "is_active",
        server_default=None,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(
        "membership",
        "is_active",
    )
