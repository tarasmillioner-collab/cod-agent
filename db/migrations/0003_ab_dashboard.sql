-- A/B-варианты и деньги для дашборда
ALTER TABLE chats ADD COLUMN variant TEXT;
ALTER TABLE chats ADD COLUMN last_name TEXT;
ALTER TABLE chats ADD COLUMN offer_slug TEXT;
ALTER TABLE orders ADD COLUMN variant TEXT;
ALTER TABLE orders ADD COLUMN offer_slug TEXT;
ALTER TABLE orders ADD COLUMN revenue_uah INTEGER;
ALTER TABLE funnel_events ADD COLUMN variant TEXT;
CREATE INDEX IF NOT EXISTS ix_funnel_variant ON funnel_events(variant, name, ts_utc);
CREATE TABLE IF NOT EXISTS voice_cache (
  key TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  created_utc TEXT NOT NULL
);
