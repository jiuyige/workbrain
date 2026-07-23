"""add document lifecycle event

Revision ID: a6d2e9f4c1b7
Revises: f4c8a1d9e2b3
Create Date: 2026-07-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6d2e9f4c1b7"
down_revision: Union[str, Sequence[str], None] = "f4c8a1d9e2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "documentlifecycleevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "document_version >= 1",
            name="ck_documentlifecycleevent_version_positive",
        ),
        sa.CheckConstraint(
            """
            (
                action = 'publish'
                AND from_status IN ('ready', 'published')
                AND to_status = 'published'
            )
            OR (
                action = 'archive'
                AND from_status IN ('published', 'archived')
                AND to_status = 'archived'
            )
            """,
            name="ck_documentlifecycleevent_transition",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_documentlifecycleevent_actor_user_id"),
        "documentlifecycleevent",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documentlifecycleevent_document_id"),
        "documentlifecycleevent",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documentlifecycleevent_organization_id"),
        "documentlifecycleevent",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_documentlifecycleevent_organization_id"),
        table_name="documentlifecycleevent",
    )
    op.drop_index(
        op.f("ix_documentlifecycleevent_document_id"),
        table_name="documentlifecycleevent",
    )
    op.drop_index(
        op.f("ix_documentlifecycleevent_actor_user_id"),
        table_name="documentlifecycleevent",
    )
    op.drop_table("documentlifecycleevent")
