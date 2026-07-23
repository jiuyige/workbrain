"""assign legacy organization

Revision ID: 95cabd7d4b36
Revises: 01ac9962e75a
Create Date: 2026-07-19 13:47:20.893956

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "95cabd7d4b36"
down_revision: Union[str, Sequence[str], None] = "01ac9962e75a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_ORGANIZATION_ID = 999_999_999
LEGACY_ORGANIZATION_NAME = "WorkBrain Legacy Workspace"
LEGACY_ORGANIZATION_SLUG = "workbrain-legacy-workspace"

RESOURCE_TABLES = (
    "document",
    "chatmessage",
    "llmcalllog",
    "todo",
    "toolcalllog",
    "agenttrace",
    "documentchunk",
    "ragquerylog",
    "documentprocesslog",
)


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()

    matching_organizations = (
        connection.execute(
            sa.text(
                """
            SELECT id, slug
            FROM organization
            WHERE id = :organization_id
               OR slug = :organization_slug
            """
            ),
            {
                "organization_id": LEGACY_ORGANIZATION_ID,
                "organization_slug": LEGACY_ORGANIZATION_SLUG,
            },
        )
        .mappings()
        .all()
    )

    if matching_organizations:
        has_expected_organization = (
            len(matching_organizations) == 1
            and matching_organizations[0]["id"] == LEGACY_ORGANIZATION_ID
            and matching_organizations[0]["slug"] == LEGACY_ORGANIZATION_SLUG
        )

        if not has_expected_organization:
            raise RuntimeError("legacy organization id or slug is already in use")
    else:
        connection.execute(
            sa.text(
                """
                INSERT INTO organization (
                    id,
                    name,
                    slug,
                    created_at
                )
                VALUES (
                    :organization_id,
                    :organization_name,
                    :organization_slug,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "organization_id": LEGACY_ORGANIZATION_ID,
                "organization_name": LEGACY_ORGANIZATION_NAME,
                "organization_slug": LEGACY_ORGANIZATION_SLUG,
            },
        )

    connection.execute(
        sa.text(
            """
            INSERT INTO membership (
                organization_id,
                user_id,
                role,
                is_active,
                created_at
            )
            SELECT
                :organization_id,
                existing_user.id,
                'member',
                TRUE,
                CURRENT_TIMESTAMP
            FROM "user" AS existing_user
            WHERE NOT EXISTS (
                SELECT 1
                FROM membership
                WHERE membership.organization_id
                    = :organization_id
                  AND membership.user_id = existing_user.id
            )
            """
        ),
        {
            "organization_id": LEGACY_ORGANIZATION_ID,
        },
    )

    for table_name in RESOURCE_TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "organization_id",
                sa.Integer(),
                nullable=False,
                server_default=sa.text(str(LEGACY_ORGANIZATION_ID)),
            ),
        )
        op.create_index(
            f"ix_{table_name}_organization_id",
            table_name,
            ["organization_id"],
            unique=False,
        )
        op.create_foreign_key(
            f"fk_{table_name}_organization_id_organization",
            table_name,
            "organization",
            ["organization_id"],
            ["id"],
        )
        op.alter_column(
            table_name,
            "organization_id",
            existing_type=sa.Integer(),
            server_default=None,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table_name in reversed(RESOURCE_TABLES):
        op.drop_constraint(
            f"fk_{table_name}_organization_id_organization",
            table_name,
            type_="foreignkey",
        )
        op.drop_index(
            f"ix_{table_name}_organization_id",
            table_name=table_name,
        )
        op.drop_column(
            table_name,
            "organization_id",
        )

    connection = op.get_bind()

    connection.execute(
        sa.text(
            """
            DELETE FROM membership
            WHERE organization_id = :organization_id
            """
        ),
        {
            "organization_id": LEGACY_ORGANIZATION_ID,
        },
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM organization
            WHERE id = :organization_id
            AND slug = :organization_slug
            """
        ),
        {
            "organization_id": LEGACY_ORGANIZATION_ID,
            "organization_slug": LEGACY_ORGANIZATION_SLUG,
        },
    )
