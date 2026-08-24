-- Спільна робота: хто веде чат і хто запустив розсилку
ALTER TABLE chats ADD COLUMN assignee TEXT;
ALTER TABLE broadcasts ADD COLUMN actor TEXT;
CREATE TABLE IF NOT EXISTS dash_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_dash_log_ts ON dash_log(id DESC);
