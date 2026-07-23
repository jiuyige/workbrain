"""add rag query log knowledge base

Revision ID: c3e7a1f9d4b2
Revises: a6d2e9f4c1b7
Create Date: 2026-07-21 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e7a1f9d4b2"
down_revision: Union[str, Sequence[str], None] = "a6d2e9f4c1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "ragquerylog",
        sa.Column("knowledge_base_id", sa.Integer(), nullable=True),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE ragquerylog AS log
            SET knowledge_base_id = single_knowledge_base.id
            FROM (
                SELECT organization_id, MIN(id) AS id
                FROM knowledgebase
                GROUP BY organization_id
                HAVING COUNT(*) = 1
            ) AS single_knowledge_base
            WHERE log.organization_id = single_knowledge_base.organization_id
            """
        )
    )

    op.create_foreign_key(
        "fk_ragquerylog_knowledge_base_id_knowledgebase",
        "ragquerylog",
        "knowledgebase",
        ["knowledge_base_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_ragquerylog_knowledge_base_id"),
        "ragquerylog",
        ["knowledge_base_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_ragquerylog_knowledge_base_id"),
        table_name="ragquerylog",
    )
    op.drop_constraint(
        "fk_ragquerylog_knowledge_base_id_knowledgebase",
        "ragquerylog",
        type_="foreignkey",
    )
    op.drop_column("ragquerylog", "knowledge_base_id")
