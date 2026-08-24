-- cod-agent schema v1. SQLite WAL. Все времена — ISO UTC (TEXT).

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings(key, value) VALUES ('bot_enabled', '1');

CREATE TABLE IF NOT EXISTS chats (
  tg_user_id    INTEGER PRIMARY KEY,
  chat_id       INTEGER NOT NULL,
  username      TEXT,
  first_name    TEXT,
  phone         TEXT,
  name          TEXT,
  utm_json      TEXT NOT NULL DEFAULT '{}',
  start_payload TEXT,
  mode          TEXT NOT NULL DEFAULT 'bot',     -- bot | human
  topic_id      INTEGER,
  flags_json    TEXT NOT NULL DEFAULT '{}',      -- downgraded, objection_price, reentry, said_only_one, no_progress...
  lang_hint     TEXT,
  created_utc   TEXT NOT NULL,
  last_seen_utc TEXT NOT NULL,
  last_bot_utc  TEXT,
  blocked_utc   TEXT,
  opted_out_utc TEXT
);

CREATE TABLE IF NOT EXISTS orders (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id         INTEGER NOT NULL REFERENCES chats(tg_user_id),
  stage           TEXT NOT NULL,
  set_code        TEXT,            -- код набора из offer.yaml (s1/s2/s3)
  price_uah       INTEGER,
  name            TEXT,
  phone           TEXT,
  np_city_ref     TEXT,
  np_city_name    TEXT,
  np_wh_ref       TEXT,
  np_wh_name      TEXT,
  delivery_type   TEXT NOT NULL DEFAULT 'warehouse',   -- warehouse | postomat | courier
  upsell_shown    INTEGER NOT NULL DEFAULT 0,
  upsell_accepted INTEGER,
  lpcrm_order_id  TEXT,
  lpcrm_status    TEXT,
  ttn             TEXT,
  np_status_code  TEXT,
  np_status_text  TEXT,
  storage_until   TEXT,            -- дата конца хранения на НП (YYYY-MM-DD), считает код
  utm_json        TEXT NOT NULL DEFAULT '{}',
  created_utc     TEXT NOT NULL,
  updated_utc     TEXT NOT NULL,
  confirmed_utc   TEXT,
  shipped_utc     TEXT,
  arrived_utc     TEXT,
  picked_utc      TEXT,
  closed_utc      TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_chat_stage ON orders(chat_id, stage);
CREATE INDEX IF NOT EXISTS ix_orders_stage ON orders(stage);
-- один активный заказ на чат
CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_active ON orders(chat_id)
  WHERE stage NOT IN ('done', 'cancelled', 'returned');

CREATE TABLE IF NOT EXISTS order_events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id  INTEGER NOT NULL REFERENCES orders(id),
  name      TEXT NOT NULL,
  dedup_key TEXT NOT NULL DEFAULT '',
  ts_utc    TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(order_id, name, dedup_key)
);

CREATE TABLE IF NOT EXISTS messages (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id       INTEGER NOT NULL,
  role          TEXT NOT NULL,      -- user | assistant | tool | manager | system
  content       TEXT NOT NULL,
  tool_json     TEXT,
  ts_utc        TEXT NOT NULL,
  tg_message_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_messages_chat ON messages(chat_id, id);

CREATE TABLE IF NOT EXISTS handoffs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id    INTEGER NOT NULL,
  order_id   INTEGER,
  topic_id   INTEGER,
  reason     TEXT,
  state      TEXT NOT NULL DEFAULT 'open',   -- open | closed
  opened_utc TEXT NOT NULL,
  closed_utc TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_handoff_open ON handoffs(chat_id) WHERE state = 'open';

CREATE TABLE IF NOT EXISTS outbox (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT NOT NULL,      -- lpcrm_create | tg_send
  ref_id       TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  state        TEXT NOT NULL DEFAULT 'pending',   -- pending | done | failed
  attempts     INTEGER NOT NULL DEFAULT 0,
  next_try_utc TEXT NOT NULL,
  last_error   TEXT,
  created_utc  TEXT NOT NULL,
  done_utc     TEXT,
  UNIQUE(kind, ref_id)
);
CREATE INDEX IF NOT EXISTS ix_outbox_due ON outbox(state, next_try_utc);

CREATE TABLE IF NOT EXISTS np_cache (
  kind        TEXT NOT NULL,       -- city | warehouse
  key         TEXT NOT NULL,
  json        TEXT NOT NULL,
  fetched_utc TEXT NOT NULL,
  PRIMARY KEY(kind, key)
);

CREATE TABLE IF NOT EXISTS llm_usage (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc     TEXT NOT NULL,
  chat_id    INTEGER,
  model      TEXT,
  in_tokens  INTEGER NOT NULL DEFAULT 0,
  out_tokens INTEGER NOT NULL DEFAULT 0,
  usd        REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS funnel_events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc    TEXT NOT NULL,
  chat_id   INTEGER,
  order_id  INTEGER,
  name      TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_funnel_name_ts ON funnel_events(name, ts_utc);
