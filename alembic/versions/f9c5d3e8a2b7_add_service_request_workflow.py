"""add service request workflow

Revision ID: f9c5d3e8a2b7
Revises: e8b4c2d7f1a6
Create Date: 2026-07-21 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "f9c5d3e8a2b7"
down_revision: Union[str, Sequence[str], None] = "e8b4c2d7f1a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "servicerequest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("requester_user_id", sa.Integer(), nullable=False),
        sa.Column("service_catalog_item_id", sa.Integer(), nullable=False),
        sa.Column(
            "title",
            sqlmodel.sql.sqltypes.AutoString(length=200),
            nullable=False,
        ),
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(length=2000),
            nullable=False,
        ),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "decision_reason",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_servicerequest_status",
        ),
        sa.CheckConstraint(
            """
            (
                status = 'pending'
                AND decided_by_user_id IS NULL
                AND decided_at IS NULL
                AND decision_reason IS NULL
            )
            OR (
                status = 'approved'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND decision_reason IS NULL
            )
            OR (
                status = 'rejected'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND decision_reason IS NOT NULL
                AND length(trim(decision_reason)) > 0
            )
            """,
            name="ck_servicerequest_decision_state",
        ),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["requester_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(
            ["service_catalog_item_id"],
            ["servicecatalogitem.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "organization_id",
        "requester_user_id",
        "service_catalog_item_id",
        "status",
        "decided_by_user_id",
    ):
        op.create_index(
            op.f(f"ix_servicerequest_{column}"),
            "servicerequest",
            [column],
            unique=False,
        )

    op.create_table(
        "servicerequestevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("service_request_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "action IN ('create', 'approve', 'reject')",
            name="ck_servicerequestevent_action",
        ),
        sa.CheckConstraint(
            """
            (
                action = 'create'
                AND from_status IS NULL
                AND to_status = 'pending'
                AND reason IS NULL
            )
            OR (
                action = 'approve'
                AND from_status = 'pending'
                AND to_status = 'approved'
                AND reason IS NULL
            )
            OR (
                action = 'reject'
                AND from_status = 'pending'
                AND to_status = 'rejected'
                AND reason IS NOT NULL
                AND length(trim(reason)) > 0
            )
            """,
            name="ck_servicerequestevent_transition",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(
            ["service_request_id"],
            ["servicerequest.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "service_request_id", "actor_user_id"):
        op.create_index(
            op.f(f"ix_servicerequestevent_{column}"),
            "servicerequestevent",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("actor_user_id", "service_request_id", "organization_id"):
        op.drop_index(
            op.f(f"ix_servicerequestevent_{column}"),
            table_name="servicerequestevent",
        )
    op.drop_table("servicerequestevent")

    for column in (
        "decided_by_user_id",
        "status",
        "service_catalog_item_id",
        "requester_user_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_servicerequest_{column}"),
            table_name="servicerequest",
        )
    op.drop_table("servicerequest")
