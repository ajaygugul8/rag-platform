-- Runs once when the postgres container's data volume is first created.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- supports fuzzy/keyword search later
