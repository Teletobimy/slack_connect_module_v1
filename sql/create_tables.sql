CREATE TABLE IF NOT EXISTS messages (
  msg_uid TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL,
  thread_ts REAL,
  ts REAL NOT NULL,
  user_id TEXT,
  text TEXT,
  edited_ts REAL,
  content_hash TEXT,
  channel_type TEXT,
  json_raw TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_user_ts    ON messages(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_thread     ON messages(thread_ts);

CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY, 
  name TEXT, 
  type TEXT, 
  is_private INTEGER
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, 
  real_name TEXT, 
  name TEXT, 
  updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_channel_state (
  channel_id TEXT PRIMARY KEY, 
  last_ts REAL
);

CREATE TABLE IF NOT EXISTS sync_thread_state (
  channel_id TEXT, 
  thread_ts REAL, 
  last_ts REAL,
  PRIMARY KEY(channel_id, thread_ts)
);

CREATE TABLE IF NOT EXISTS metrics_weekly (
  user_id TEXT,
  week_start DATE,
  message_count INTEGER,
  active_days INTEGER,
  avg_gap_h REAL,
  max_gap_h REAL,
  done_signals INTEGER,
  blocker_signals INTEGER,
  checklist_total INTEGER,
  checklist_done INTEGER,
  mention_count INTEGER,
  top_channels_json TEXT,
  channel_coverage_ratio REAL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(user_id, week_start)
);

CREATE TABLE IF NOT EXISTS gpt_analyses (
  id SERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  week_start DATE NOT NULL,
  week_range TEXT,
  analysis_text TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, week_start)
);

CREATE INDEX IF NOT EXISTS idx_gpt_analyses_user_week ON gpt_analyses(user_id, week_start);

