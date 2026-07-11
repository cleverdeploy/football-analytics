"""Run the full ingest pipeline in order, then refit the goal model.

Usage: python3 ingest/run_all.py [--force]   (--force refetches cached pages)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compute_elo
import fetch_lineups
import fetch_results
import fetch_squads
import fetch_values
from db import get_conn
from model.predict import fit_goal_model

force = "--force" in sys.argv

print("== results ==")
fetch_results.load(fetch_results.fetch(force))
print("== elo ==")
compute_elo.run()
print("== squads ==")
fetch_squads.run(force)
print("== lineups ==")
fetch_lineups.run(force)
print("== market values ==")
fetch_values.run()
print("== goal model ==")
conn = get_conn()
a, b = fit_goal_model(conn)
print(f"log lambda = {a:.4f} + {b:.6f} * elo_diff")

for table in ("matches", "elo_ratings", "players", "lineups"):
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"{table}: {n} rows")
missing = conn.execute("SELECT COUNT(*) FROM players WHERE value_eur IS NULL").fetchone()[0]
print(f"players missing value: {missing}")
conn.close()
