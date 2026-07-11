CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE documentchunk
ADD COLUMN IF NOT EXISTS embedding_vector vector(1536);

UPDATE documentchunk
SET embedding_vector = embedding_json::vector(1536)
WHERE embedding_json IS NOT NULL
  AND embedding_vector IS NULL;
