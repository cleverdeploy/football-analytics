"""SQLite helpers shared by ingest scripts, model, and the Flask app."""
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "football.db")
CACHE_DIR = os.path.join(ROOT, "data", "cache")

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    tournament TEXT,
    city TEXT,
    country TEXT,
    neutral INTEGER NOT NULL DEFAULT 0,
    home_elo_pre REAL,
    away_elo_pre REAL
);
CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches (home_team, away_team, date);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches (date);

CREATE TABLE IF NOT EXISTS elo_ratings (
    team TEXT PRIMARY KEY,
    rating REAL NOT NULL,
    matches INTEGER NOT NULL,
    last_match TEXT
);

CREATE TABLE IF NOT EXISTS elo_history (
    team TEXT NOT NULL,
    date TEXT NOT NULL,
    rating REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_elo_history ON elo_history (team, date);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    team TEXT NOT NULL,
    name TEXT NOT NULL,
    position TEXT NOT NULL,          -- GK / DF / MF / FW
    shirt_no INTEGER,
    dob TEXT,
    age INTEGER,
    caps INTEGER DEFAULT 0,
    goals INTEGER DEFAULT 0,
    club TEXT,
    value_eur REAL,
    value_source TEXT,               -- transfermarkt / heuristic
    status TEXT DEFAULT 'fit',       -- fit / doubtful / out
    status_note TEXT,
    UNIQUE (team, name)
);

CREATE TABLE IF NOT EXISTS lineups (
    team TEXT PRIMARY KEY,
    formation TEXT,
    xi_json TEXT,                    -- JSON list of player names in slot order
    source TEXT,
    fetched TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default
