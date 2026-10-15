PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    google_sub  TEXT UNIQUE NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT,              -- NULL until onboarding done
    phone       TEXT,
    disabled    INTEGER NOT NULL DEFAULT 0,
    disabled_until TEXT,           -- set = temporary; NULL with disabled=1 = until re-enabled
    created_at  TEXT NOT NULL
);

-- Trucks, sites and verbs in one table. An alias is just a row merged into another.
CREATE TABLE IF NOT EXISTS registry (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('truck', 'site', 'verb')),
    code        TEXT NOT NULL,
    label       TEXT NOT NULL,
    site_type   TEXT CHECK (site_type IN ('loading', 'unloading', 'depot')),
    plate       TEXT NOT NULL DEFAULT '',   -- trucks: licence / registration number
    notes       TEXT NOT NULL DEFAULT '',   -- free remarks (driver, owner, capacity...)
    merged_into INTEGER REFERENCES registry(id),
    active      INTEGER NOT NULL DEFAULT 1,
    sort        INTEGER NOT NULL DEFAULT 0,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL,
    UNIQUE (kind, code COLLATE NOCASE)
);

CREATE TABLE IF NOT EXISTS shifts (
    id              INTEGER PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    default_site_id INTEGER REFERENCES registry(id),
    started_by      INTEGER REFERENCES users(id),
    ended_by        INTEGER REFERENCES users(id),
    deleted         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    source      TEXT NOT NULL DEFAULT 'web' CHECK (source IN ('web', 'wa')),
    verb_id     INTEGER NOT NULL REFERENCES registry(id),
    site_id     INTEGER REFERENCES registry(id),
    event_time  TEXT NOT NULL,         -- ISO-8601, IST offset
    remarks     TEXT NOT NULL DEFAULT '',
    deleted     INTEGER NOT NULL DEFAULT 0,
    wa_msg_id   TEXT,                  -- WA message this report was relayed as / parsed from
    skip_fleet  INTEGER NOT NULL DEFAULT 0,  -- admin chose: don't relay this report to the fleet group
    half        INTEGER NOT NULL DEFAULT 0,  -- half load: counts as 1 trolley, ½ in the absolute count
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_time ON reports(event_time);
CREATE INDEX IF NOT EXISTS reports_user ON reports(user_id);

CREATE TABLE IF NOT EXISTS report_trucks (
    report_id   INTEGER NOT NULL REFERENCES reports(id),
    truck_id    INTEGER NOT NULL REFERENCES registry(id),
    PRIMARY KEY (report_id, truck_id)
);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    user_id     INTEGER REFERENCES users(id),
    action      TEXT NOT NULL,         -- create | update | delete | merge | unmerge | ...
    entity      TEXT NOT NULL,         -- report | shift | registry | user | setting
    entity_id   INTEGER,
    before      TEXT,                  -- JSON
    after       TEXT                   -- JSON
);

-- Pending WhatsApp sends. Phase 2 relay worker drains this.
CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL,         -- report | edit | delete | shift | summary
    payload     TEXT NOT NULL,         -- JSON
    sent_at     TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'   -- pending | sent | skipped | failed
);

-- Every WhatsApp message in or out. Links reports to the messages that carried them,
-- so edits/deletes can reply to the original.
CREATE TABLE IF NOT EXISTS wa_log (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    jid         TEXT NOT NULL,
    wa_id       TEXT,
    kind        TEXT NOT NULL,         -- out: report|edit|delete|shift|summary|ack|ask|reply   in: event|command|chat|unparsed
    report_id   INTEGER REFERENCES reports(id),
    sender      TEXT,                  -- in: sender jid / name
    text        TEXT NOT NULL,
    from_me     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS wa_log_report ON wa_log(report_id);
CREATE INDEX IF NOT EXISTS wa_log_waid ON wa_log(wa_id);

-- Loads/unloads of trucks nobody reported (untracked trucks), added by hand to a shift's summary.
CREATE TABLE IF NOT EXISTS manual_counts (
    id          INTEGER PRIMARY KEY,
    shift_id    INTEGER NOT NULL REFERENCES shifts(id),
    truck       TEXT NOT NULL,         -- registry code, or free text for trucks not in the registry
    kind        TEXT NOT NULL CHECK (kind IN ('load', 'unload')),
    count       INTEGER NOT NULL CHECK (count > 0),
    site        TEXT,                  -- registry site code
    note        TEXT NOT NULL DEFAULT '',
    post_fleet  INTEGER NOT NULL DEFAULT 1, -- also relay to the fleet group (control always)
    half        INTEGER NOT NULL DEFAULT 0, -- half loads: count 1 each, ½ each in the absolute count
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    deleted     INTEGER NOT NULL DEFAULT 0
);

-- Read-only API keys for scripts / downstream apps. Only a hash is stored.
CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    prefix      TEXT NOT NULL,          -- first characters, to recognise a key in the list
    hash        TEXT NOT NULL UNIQUE,   -- sha256 of the key
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL,
    last_used_at TEXT,
    revoked     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
