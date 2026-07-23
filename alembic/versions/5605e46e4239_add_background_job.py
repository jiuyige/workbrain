"""add background job

Revision ID: 5605e46e4239
Revises: 95cabd7d4b36
Create Date: 2026-07-19 15:54:32.137427

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5605e46e4239"
down_revision: Union[str, Sequence[str], None] = "95cabd7d4b36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "backgroundjob",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "job_type",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False,
        ),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column(
            "celery_task_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "length(trim(job_type)) BETWEEN 1 AND 50",
            name="ck_backgroundjob_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_backgroundjob_status",
        ),
        sa.CheckConstraint(
            """
            (
                status = 'queued'
                AND started_at IS NULL
                AND finished_at IS NULL
            )
            OR (
                status = 'running'
                AND started_at IS NOT NULL
                AND finished_at IS NULL
            )
            OR (
                status IN ('succeeded', 'failed')
                AND started_at IS NOT NULL
                AND finished_at IS NOT NULL
            )
            OR (
                status = 'cancelled'
                AND finished_at IS NOT NULL
            )
            """,
            name="ck_backgroundjob_status_timestamps",
        ),
        sa.CheckConstraint(
            """
            (
                status = 'failed'
                AND error_message IS NOT NULL
                AND length(trim(error_message)) > 0
            )
            OR (
                status != 'failed'
                AND error_message IS NULL
            )
            """,
            name="ck_backgroundjob_error_message",
        ),
        sa.CheckConstraint(
            """
            (started_at IS NULL OR started_at >= created_at)
            AND (finished_at IS NULL OR finished_at >= created_at)
            AND (
                started_at IS NULL
                OR finished_at IS NULL
                OR finished_at >= started_at
            )
            """,
            name="ck_backgroundjob_timestamp_order",
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
    )
    op.create_index(
        op.f("ix_backgroundjob_celery_task_id"),
        "backgroundjob",
        ["celery_task_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_backgroundjob_created_by_user_id"),
        "backgroundjob",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_backgroundjob_organization_id"),
        "backgroundjob",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_backgroundjob_organization_id"),
        table_name="backgroundjob",
    )
    op.drop_index(
        op.f("ix_backgroundjob_created_by_user_id"),
        table_name="backgroundjob",
    )
    op.drop_index(
        op.f("ix_backgroundjob_celery_task_id"),
        table_name="backgroundjob",
    )
    op.drop_table("backgroundjob")
