"""Elo difference -> expected goals -> Poisson outcome probabilities.

The Elo->goals map (log lambda = a + b * elo_diff) is fitted once from the
historical matches table (both perspectives of every match, modern era) and
stored in meta. Knockout draws resolve through extra time + penalties.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_conn, get_meta, set_meta
from model.config import (CALIB_MIN_DATE, ET_RATE_FACTOR, HOME_ADV,
                          LAMBDA_MAX, LAMBDA_MIN, MAX_GOALS, PENS_SPLIT)


def fit_goal_model(conn):
    rows = conn.execute(
        "SELECT home_elo_pre, away_elo_pre, home_score, away_score, neutral"
        " FROM matches WHERE home_elo_pre IS NOT NULL AND date >= ?",
        (CALIB_MIN_DATE,)).fetchall()
    drs, goals = [], []
    for r in rows:
        dr = r["home_elo_pre"] - r["away_elo_pre"] + (0 if r["neutral"] else HOME_ADV)
        drs.extend((dr, -dr))
        goals.extend((r["home_score"], r["away_score"]))
    drs, goals = np.array(drs), np.array(goals, dtype=float)

    edges = np.arange(-650, 700, 50)
    centers, means, weights = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (drs >= lo) & (drs < hi)
        n = int(mask.sum())
        if n >= 200:
            centers.append((lo + hi) / 2)
            means.append(goals[mask].mean())
            weights.append(n)
    b, a = np.polyfit(np.array(centers), np.log(np.array(means)), 1, w=np.sqrt(weights))
    set_meta(conn, "goal_model", {"a": float(a), "b": float(b),
                                  "n_matches": len(rows), "n_bins": len(centers)})
    return a, b


def goal_model(conn):
    gm = get_meta(conn, "goal_model")
    if gm is None:
        a, b = fit_goal_model(conn)
        return {"a": a, "b": b}
    return gm


def lambdas(conn, elo_a, elo_b, venue="neutral"):
    """Expected goals for sides A and B. venue: neutral | home_a | home_b."""
    gm = goal_model(conn)
    dr = elo_a - elo_b + (HOME_ADV if venue == "home_a" else -HOME_ADV if venue == "home_b" else 0)
    la = math.exp(gm["a"] + gm["b"] * dr)
    lb = math.exp(gm["a"] - gm["b"] * dr)
    clamp = lambda x: max(LAMBDA_MIN, min(LAMBDA_MAX, x))
    return clamp(la), clamp(lb), dr


def poisson_vector(lam, kmax=MAX_GOALS):
    ks = np.arange(kmax + 1)
    log_p = -lam + ks * math.log(lam) - np.array([math.lgamma(k + 1) for k in ks])
    p = np.exp(log_p)
    p[-1] += max(0.0, 1.0 - p.sum())  # fold the tail into the top bin
    return p


def outcome_probs(la, lb, kmax=MAX_GOALS):
    grid = np.outer(poisson_vector(la, kmax), poisson_vector(lb, kmax))
    win = float(np.tril(grid, -1).sum())
    draw = float(np.trace(grid))
    loss = float(np.triu(grid, 1).sum())
    return win, draw, loss, grid


def top_scorelines(grid, n=6):
    flat = [((i, j), float(grid[i, j])) for i in range(grid.shape[0]) for j in range(grid.shape[1])]
    flat.sort(key=lambda t: -t[1])
    return [{"score": f"{i}-{j}", "prob": p} for (i, j), p in flat[:n]]


def predict_match(conn, elo_a, elo_b, venue="neutral", knockout=True):
    la, lb, dr = lambdas(conn, elo_a, elo_b, venue)
    win, draw, loss, grid = outcome_probs(la, lb)
    out = {
        "elo_diff": dr, "lambda_a": la, "lambda_b": lb,
        "p_win": win, "p_draw": draw, "p_loss": loss,
        "scorelines": top_scorelines(grid),
        "elo_expectation": 1.0 / (1.0 + 10.0 ** (-dr / 400.0)),
    }
    if knockout:
        etw, etd, etl, _ = outcome_probs(la * ET_RATE_FACTOR, lb * ET_RATE_FACTOR)
        p_et_a = etw + etd * PENS_SPLIT
        out["p_advance_a"] = win + draw * p_et_a
        out["p_advance_b"] = loss + draw * (etl + etd * (1 - PENS_SPLIT))
        out["et_breakdown"] = {"p_et_win": etw, "p_et_draw": etd, "p_pens_share": PENS_SPLIT}
    return out


if __name__ == "__main__":
    conn = get_conn()
    a, b = fit_goal_model(conn)
    print(f"goal model: log lambda = {a:.4f} + {b:.6f} * elo_diff")
    for gap in (0, 100, 200, 400):
        la, lb, _ = lambdas(conn, 2000 + gap, 2000)
        print(f"  elo diff +{gap}: xG {la:.2f} vs {lb:.2f}")
    eng = conn.execute("SELECT rating FROM elo_ratings WHERE team='England'").fetchone()[0]
    nor = conn.execute("SELECT rating FROM elo_ratings WHERE team='Norway'").fetchone()[0]
    p = predict_match(conn, eng, nor)
    print(f"England ({eng:.0f}) v Norway ({nor:.0f}):"
          f" W {p['p_win']:.1%} D {p['p_draw']:.1%} L {p['p_loss']:.1%}"
          f" | advance {p['p_advance_a']:.1%}")
    conn.close()
