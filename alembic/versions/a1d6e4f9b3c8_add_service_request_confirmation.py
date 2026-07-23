"""add service request confirmation

Revision ID: a1d6e4f9b3c8
Revises: f9c5d3e8a2b7
Create Date: 2026-07-21 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "a1d6e4f9b3c8"
down_revision: Union[str, Sequence[str], None] = "f9c5d3e8a2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "servicerequestconfirmation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("requester_user_id", sa.Integer(), nullable=False),
        sa.Column("service_catalog_item_id", sa.Integer(), nullable=False),
        sa.Column(
            "confirmation_token_hash",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
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
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("service_request_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            """
            (
                service_request_id IS NULL
                AND confirmed_at IS NULL
            )
            OR (
                service_request_id IS NOT NULL
                AND confirmed_at IS NOT NULL
            )
            """,
            name="ck_servicerequestconfirmation_consumption_state",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_catalog_item_id"],
            ["servicecatalogitem.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_request_id"],
            ["servicerequest.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "organization_id",
        "requester_user_id",
        "service_catalog_item_id",
        "expires_at",
    ):
        op.create_index(
            op.f(f"ix_servicerequestconfirmation_{column}"),
            "servicerequestconfirmation",
            [column],
            unique=False,
        )
    op.create_index(
        op.f("ix_servicerequestconfirmation_confirmation_token_hash"),
        "servicerequestconfirmation",
        ["confirmation_token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_servicerequestconfirmation_service_request_id"),
        "servicerequestconfirmation",
        ["service_request_id"],
        unique=True,
    )


def downgrade() -> None:
    for column in (
        "service_request_id",
        "confirmation_token_hash",
        "expires_at",
        "service_catalog_item_id",
        "requester_user_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_servicerequestconfirmation_{column}"),
            table_name="servicerequestconfirmation",
        )
    op.drop_table("servicerequestconfirmation")
