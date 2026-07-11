"""Download the full international results dataset (1872-present) into the matches table."""
import os
import sys

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import CACHE_DIR, get_conn

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"


def fetch(force=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "results.csv")
    if force or not os.path.exists(cache):
        resp = requests.get(URL, timeout=60)
        resp.raise_for_status()
        with open(cache, "wb") as f:
            f.write(resp.content)
        print(f"downloaded {len(resp.content) // 1024} KB -> {cache}")
    return cache


def load(cache):
    df = pd.read_csv(cache)
    df = df.dropna(subset=["home_score", "away_score"])
    df["neutral"] = df["neutral"].astype(str).str.upper().eq("TRUE").astype(int)
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)

    conn = get_conn()
    conn.execute("DELETE FROM matches")
    conn.executemany(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score,"
        " tournament, city, country, neutral) VALUES (?,?,?,?,?,?,?,?,?)",
        df[["date", "home_team", "away_team", "home_score", "away_score",
            "tournament", "city", "country", "neutral"]].itertuples(index=False),
    )
    conn.commit()
    n, lo, hi = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM matches").fetchone()
    print(f"matches: {n} rows, {lo} .. {hi}")
    conn.close()


if __name__ == "__main__":
    load(fetch(force="--force" in sys.argv))
