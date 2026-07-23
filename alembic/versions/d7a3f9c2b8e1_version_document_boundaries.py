"""version document boundaries

Revision ID: d7a3f9c2b8e1
Revises: b2f4c8d1e6a7
Create Date: 2026-07-19 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a3f9c2b8e1"
down_revision: Union[str, Sequence[str], None] = "b2f4c8d1e6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_ORGANIZATION_ID = 999_999_999
LEGACY_KNOWLEDGE_BASE_ID = 999_999_999
LEGACY_KNOWLEDGE_BASE_NAME = "Legacy Documents"


def _knowledge_base_for_organization(
    connection: sa.Connection,
    organization_id: int,
    created_by_user_id: int,
) -> int:
    existing_id = connection.execute(
        sa.text(
            """
            SELECT id
            FROM knowledgebase
            WHERE organization_id = :organization_id
              AND name = :name
            """
        ),
        {
            "organization_id": organization_id,
            "name": LEGACY_KNOWLEDGE_BASE_NAME,
        },
    ).scalar_one_or_none()

    if existing_id is not None:
        if (
            organization_id == LEGACY_ORGANIZATION_ID
            and existing_id != LEGACY_KNOWLEDGE_BASE_ID
        ):
            raise RuntimeError(
                "legacy knowledge base name is already used by another record"
            )

        return existing_id

    values = {
        "organization_id": organization_id,
        "created_by_user_id": created_by_user_id,
        "name": LEGACY_KNOWLEDGE_BASE_NAME,
    }

    if organization_id == LEGACY_ORGANIZATION_ID:
        values["knowledge_base_id"] = LEGACY_KNOWLEDGE_BASE_ID
        return connection.execute(
            sa.text(
                """
                INSERT INTO knowledgebase (
                    id,
                    organization_id,
                    created_by_user_id,
                    name,
                    description,
                    created_at,
                    updated_at
                )
                VALUES (
                    :knowledge_base_id,
                    :organization_id,
                    :created_by_user_id,
                    :name,
                    'Compatibility home for documents created before knowledge bases.',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            values,
        ).scalar_one()

    return connection.execute(
        sa.text(
            """
            INSERT INTO knowledgebase (
                organization_id,
                created_by_user_id,
                name,
                description,
                created_at,
                updated_at
            )
            VALUES (
                :organization_id,
                :created_by_user_id,
                :name,
                'Compatibility home for documents created before knowledge bases.',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            RETURNING id
            """
        ),
        values,
    ).scalar_one()


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "document",
        sa.Column("knowledge_base_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "document",
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
            server_default="uploaded",
        ),
    )

    connection = op.get_bind()
    organizations = connection.execute(
        sa.text(
            """
            SELECT organization_id, MIN(owner_id) AS created_by_user_id
            FROM document
            GROUP BY organization_id
            """
        )
    ).mappings()

    organizations_with_documents = {
        row["organization_id"]: row["created_by_user_id"] for row in organizations
    }

    legacy_creator_id = connection.execute(
        sa.text(
            """
            SELECT MIN(user_id)
            FROM membership
            WHERE organization_id = :organization_id
            """
        ),
        {"organization_id": LEGACY_ORGANIZATION_ID},
    ).scalar_one_or_none()

    if legacy_creator_id is not None:
        organizations_with_documents.setdefault(
            LEGACY_ORGANIZATION_ID,
            legacy_creator_id,
        )

    for organization_id, created_by_user_id in organizations_with_documents.items():
        knowledge_base_id = _knowledge_base_for_organization(
            connection,
            organization_id,
            created_by_user_id,
        )
        connection.execute(
            sa.text(
                """
                UPDATE document
                SET knowledge_base_id = :knowledge_base_id,
                    version = 1,
                    status = CASE
                        WHEN is_extracted THEN 'ready'
                        ELSE 'uploaded'
                    END
                WHERE organization_id = :organization_id
                """
            ),
            {
                "knowledge_base_id": knowledge_base_id,
                "organization_id": organization_id,
            },
        )

    missing_document_boundaries = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM document
            WHERE knowledge_base_id IS NULL
            """
        )
    ).scalar_one()

    if missing_document_boundaries:
        raise RuntimeError("documents could not be assigned to a knowledge base")

    op.alter_column(
        "document",
        "knowledge_base_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "document",
        "version",
        existing_type=sa.Integer(),
        server_default=None,
    )
    op.alter_column(
        "document",
        "status",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=20),
        server_default=None,
    )
    op.create_foreign_key(
        "fk_document_knowledge_base_id_knowledgebase",
        "document",
        "knowledgebase",
        ["knowledge_base_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_document_version_positive",
        "document",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_document_status",
        "document",
        "status IN ('uploaded', 'processing', 'ready', 'published', 'archived')",
    )
    op.create_index(
        op.f("ix_document_knowledge_base_id"),
        "document",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_status"),
        "document",
        ["status"],
        unique=False,
    )

    op.add_column(
        "documentchunk",
        sa.Column("knowledge_base_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "documentchunk",
        sa.Column(
            "document_version",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "documentchunk",
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=True,
        ),
    )

    connection.execute(
        sa.text(
            """
            UPDATE documentchunk AS chunk
            SET organization_id = document.organization_id,
                knowledge_base_id = document.knowledge_base_id,
                document_version = document.version,
                status = document.status
            FROM document
            WHERE chunk.document_id = document.id
            """
        )
    )

    orphan_chunk_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM documentchunk
            WHERE knowledge_base_id IS NULL
               OR document_version IS NULL
               OR status IS NULL
            """
        )
    ).scalar_one()

    if orphan_chunk_count:
        raise RuntimeError("orphan document chunks must be repaired before migration")

    op.alter_column(
        "documentchunk",
        "knowledge_base_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "documentchunk",
        "document_version",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "documentchunk",
        "status",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=20),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_documentchunk_knowledge_base_id_knowledgebase",
        "documentchunk",
        "knowledgebase",
        ["knowledge_base_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_documentchunk_document_id_document",
        "documentchunk",
        "document",
        ["document_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_documentchunk_document_version_positive",
        "documentchunk",
        "document_version >= 1",
    )
    op.create_check_constraint(
        "ck_documentchunk_status",
        "documentchunk",
        "status IN ('uploaded', 'processing', 'ready', 'published', 'archived')",
    )
    op.create_index(
        op.f("ix_documentchunk_knowledge_base_id"),
        "documentchunk",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documentchunk_status"),
        "documentchunk",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_documentchunk_status"),
        table_name="documentchunk",
    )
    op.drop_index(
        op.f("ix_documentchunk_knowledge_base_id"),
        table_name="documentchunk",
    )
    op.drop_constraint(
        "ck_documentchunk_status",
        "documentchunk",
        type_="check",
    )
    op.drop_constraint(
        "ck_documentchunk_document_version_positive",
        "documentchunk",
        type_="check",
    )
    op.drop_constraint(
        "fk_documentchunk_document_id_document",
        "documentchunk",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentchunk_knowledge_base_id_knowledgebase",
        "documentchunk",
        type_="foreignkey",
    )
    op.drop_column("documentchunk", "status")
    op.drop_column("documentchunk", "document_version")
    op.drop_column("documentchunk", "knowledge_base_id")

    op.drop_index(
        op.f("ix_document_status"),
        table_name="document",
    )
    op.drop_index(
        op.f("ix_document_knowledge_base_id"),
        table_name="document",
    )
    op.drop_constraint(
        "ck_document_status",
        "document",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_version_positive",
        "document",
        type_="check",
    )
    op.drop_constraint(
        "fk_document_knowledge_base_id_knowledgebase",
        "document",
        type_="foreignkey",
    )
    op.drop_column("document", "status")
    op.drop_column("document", "version")
    op.drop_column("document", "knowledge_base_id")
