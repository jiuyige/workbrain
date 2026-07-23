import subprocess
import sys

from sqlalchemy import create_engine, text

from app.config import DATABASE_URL
from app.models import (
    LEGACY_KNOWLEDGE_BASE_ID,
    LEGACY_KNOWLEDGE_BASE_NAME,
    LEGACY_ORGANIZATION_ID,
    LEGACY_ORGANIZATION_SLUG,
)

PREVIOUS_REVISION = "01ac9962e75a"

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

engine = create_engine(DATABASE_URL)

if engine.dialect.name != "postgresql":
    raise RuntimeError("legacy migration check requires PostgreSQL")


def seed_legacy_data() -> tuple[int, int]:
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                """
                INSERT INTO "user" (
                    username,
                    hashed_password
                )
                VALUES (
                    'legacy-migration-user',
                    'legacy-password-hash'
                )
                RETURNING id
                """
            )
        ).scalar_one()

        document_id = connection.execute(
            text(
                """
                INSERT INTO document (
                    owner_id,
                    original_filename,
                    stored_filename,
                    file_path,
                    content_type,
                    extracted_text,
                    is_extracted
                )
                VALUES (
                    :owner_id,
                    'legacy.txt',
                    'legacy-stored.txt',
                    '/tmp/legacy-stored.txt',
                    'text/plain',
                    'legacy document content',
                    TRUE
                )
                RETURNING id
                """
            ),
            {"owner_id": user_id},
        ).scalar_one()

        connection.execute(
            text(
                """
                INSERT INTO todo (
                    owner_id,
                    title,
                    priority,
                    is_done,
                    created_at
                )
                VALUES (
                    :owner_id,
                    'legacy todo',
                    'medium',
                    FALSE,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {"owner_id": user_id},
        )

        connection.execute(
            text(
                """
                INSERT INTO llmcalllog (
                    owner_id,
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    prompt_cache_hit_tokens,
                    prompt_cache_miss_tokens,
                    estimated_cost_usd,
                    created_at
                )
                VALUES (
                    :owner_id,
                    'legacy-model',
                    1,
                    1,
                    2,
                    0,
                    1,
                    0,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {"owner_id": user_id},
        )

        return user_id, document_id


def run_upgrade() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        check=True,
    )


def verify_migrated_data(
    user_id: int,
    document_id: int,
) -> None:
    with engine.connect() as connection:
        organization_slug = connection.execute(
            text(
                """
                SELECT slug
                FROM organization
                WHERE id = :organization_id
                """
            ),
            {
                "organization_id": LEGACY_ORGANIZATION_ID,
            },
        ).scalar_one()

        assert organization_slug == LEGACY_ORGANIZATION_SLUG

        membership_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM membership
                WHERE organization_id = :organization_id
                  AND user_id = :user_id
                  AND is_active = TRUE
                """
            ),
            {
                "organization_id": LEGACY_ORGANIZATION_ID,
                "user_id": user_id,
            },
        ).scalar_one()

        assert membership_count == 1

        todo_title = connection.execute(
            text(
                """
                SELECT title
                FROM todo
                WHERE owner_id = :owner_id
                  AND organization_id = :organization_id
                """
            ),
            {
                "owner_id": user_id,
                "organization_id": LEGACY_ORGANIZATION_ID,
            },
        ).scalar_one()

        assert todo_title == "legacy todo"

        document_metadata = connection.execute(
            text(
                """
                SELECT
                    original_filename,
                    knowledge_base_id,
                    version,
                    status
                FROM document
                WHERE id = :document_id
                  AND organization_id = :organization_id
                """
            ),
            {
                "document_id": document_id,
                "organization_id": LEGACY_ORGANIZATION_ID,
            },
        ).one()

        assert document_metadata.original_filename == "legacy.txt"
        assert document_metadata.knowledge_base_id == LEGACY_KNOWLEDGE_BASE_ID
        assert document_metadata.version == 1
        assert document_metadata.status == "ready"

        knowledge_base = connection.execute(
            text(
                """
                SELECT organization_id, name
                FROM knowledgebase
                WHERE id = :knowledge_base_id
                """
            ),
            {"knowledge_base_id": LEGACY_KNOWLEDGE_BASE_ID},
        ).one()

        assert knowledge_base.organization_id == LEGACY_ORGANIZATION_ID
        assert knowledge_base.name == LEGACY_KNOWLEDGE_BASE_NAME

        log_model = connection.execute(
            text(
                """
                SELECT model
                FROM llmcalllog
                WHERE owner_id = :owner_id
                  AND organization_id = :organization_id
                """
            ),
            {
                "owner_id": user_id,
                "organization_id": LEGACY_ORGANIZATION_ID,
            },
        ).scalar_one()

        assert log_model == "legacy-model"

        for table_name in RESOURCE_TABLES:
            nullable_value = connection.execute(
                text(
                    """
                    SELECT is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                      AND column_name = 'organization_id'
                    """
                ),
                {"table_name": table_name},
            ).scalar_one()

            assert nullable_value == "NO"

            null_count = connection.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM {table_name}
                    WHERE organization_id IS NULL
                    """
                )
            ).scalar_one()

            assert null_count == 0


if __name__ == "__main__":
    seed_user_id, seed_document_id = seed_legacy_data()
    run_upgrade()
    verify_migrated_data(
        seed_user_id,
        seed_document_id,
    )

    print("legacy organization migration verified")
