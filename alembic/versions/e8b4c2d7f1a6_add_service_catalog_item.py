"""add service catalog item

Revision ID: e8b4c2d7f1a6
Revises: c3e7a1f9d4b2
Create Date: 2026-07-21 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b4c2d7f1a6"
down_revision: Union[str, Sequence[str], None] = "c3e7a1f9d4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "servicecatalogitem",
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
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 100",
            name="ck_servicecatalogitem_name_length",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_servicecatalogitem_organization_name",
        ),
    )
    op.create_index(
        op.f("ix_servicecatalogitem_created_by_user_id"),
        "servicecatalogitem",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_servicecatalogitem_is_active"),
        "servicecatalogitem",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_servicecatalogitem_organization_id"),
        "servicecatalogitem",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_servicecatalogitem_organization_id"),
        table_name="servicecatalogitem",
    )
    op.drop_index(
        op.f("ix_servicecatalogitem_is_active"),
        table_name="servicecatalogitem",
    )
    op.drop_index(
        op.f("ix_servicecatalogitem_created_by_user_id"),
        table_name="servicecatalogitem",
    )
    op.drop_table("servicecatalogitem")
