"""Compute Elo ratings for every nation from the matches table.

World Football Elo conventions: K scaled by match importance, goal-difference
multiplier, +100 home advantage unless the venue is neutral. Also back-fills
each match's pre-match ratings (used later to calibrate the Elo->goals map).
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_conn

HOME_ADV = 100.0
START_RATING = 1500.0

CONTINENTAL_FINALS = (
    "uefa euro", "copa américa", "copa america", "african cup of nations",
    "africa cup of nations", "afc asian cup", "concacaf championship",
    "gold cup", "confederations cup", "oceania nations cup",
)


def k_factor(tournament):
    t = (tournament or "").lower()
    if t == "fifa world cup":
        return 60.0
    if "qualification" in t or "nations league" in t:
        return 40.0
    if any(name in t for name in CONTINENTAL_FINALS):
        return 50.0
    if t == "friendly":
        return 20.0
    return 30.0


def goal_multiplier(diff):
    if diff <= 1:
        return 1.0
    if diff == 2:
        return 1.5
    return (11.0 + diff) / 8.0


def expected(dr):
    return 1.0 / (1.0 + 10.0 ** (-dr / 400.0))


def run():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, date, home_team, away_team, home_score, away_score,"
        " tournament, neutral FROM matches ORDER BY date, id"
    ).fetchall()

    ratings = defaultdict(lambda: START_RATING)
    counts = defaultdict(int)
    last = {}
    pre_updates, history = [], []

    for m in rows:
        h, a = m["home_team"], m["away_team"]
        rh, ra = ratings[h], ratings[a]
        pre_updates.append((rh, ra, m["id"]))

        dr = rh - ra + (0.0 if m["neutral"] else HOME_ADV)
        we = expected(dr)
        diff = m["home_score"] - m["away_score"]
        w = 1.0 if diff > 0 else 0.0 if diff < 0 else 0.5
        delta = k_factor(m["tournament"]) * goal_multiplier(abs(diff)) * (w - we)

        ratings[h] = rh + delta
        ratings[a] = ra - delta
        counts[h] += 1
        counts[a] += 1
        last[h] = last[a] = m["date"]
        history.append((h, m["date"], ratings[h]))
        history.append((a, m["date"], ratings[a]))

    conn.executemany("UPDATE matches SET home_elo_pre = ?, away_elo_pre = ? WHERE id = ?", pre_updates)
    conn.execute("DELETE FROM elo_ratings")
    conn.executemany(
        "INSERT INTO elo_ratings (team, rating, matches, last_match) VALUES (?,?,?,?)",
        [(t, r, counts[t], last[t]) for t, r in ratings.items()],
    )
    conn.execute("DELETE FROM elo_history")
    conn.executemany("INSERT INTO elo_history (team, date, rating) VALUES (?,?,?)", history)
    conn.commit()

    top = conn.execute("SELECT team, rating FROM elo_ratings ORDER BY rating DESC LIMIT 15").fetchall()
    print("top 15:")
    for i, r in enumerate(top, 1):
        print(f"  {i:2d}. {r['team']:<15} {r['rating']:.0f}")
    for t in ("England", "Norway", "Argentina", "Switzerland", "France", "Spain"):
        row = conn.execute("SELECT rating, matches FROM elo_ratings WHERE team = ?", (t,)).fetchone()
        print(f"  {t}: {row['rating']:.0f} ({row['matches']} matches)" if row else f"  {t}: MISSING")
    conn.close()


if __name__ == "__main__":
    run()
