-- Index for vector similarity search (pgvector)
CREATE INDEX IF NOT EXISTS idx_sources_embedding ON sources USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
