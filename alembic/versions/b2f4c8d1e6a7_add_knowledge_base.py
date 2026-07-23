"""add knowledge base

Revision ID: b2f4c8d1e6a7
Revises: 5605e46e4239
Create Date: 2026-07-19 16:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2f4c8d1e6a7"
down_revision: Union[str, Sequence[str], None] = "5605e46e4239"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "knowledgebase",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "name",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=False,
        ),
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 100",
            name="ck_knowledgebase_name_length",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_knowledgebase_organization_name",
        ),
    )
    op.create_index(
        op.f("ix_knowledgebase_created_by_user_id"),
        "knowledgebase",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledgebase_organization_id"),
        "knowledgebase",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_knowledgebase_organization_id"),
        table_name="knowledgebase",
    )
    op.drop_index(
        op.f("ix_knowledgebase_created_by_user_id"),
        table_name="knowledgebase",
    )
    op.drop_table("knowledgebase")
