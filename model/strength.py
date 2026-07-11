"""Lineup quality -> Elo adjustment.

A team's Elo reflects its typical full-strength side, so the best possible XI
anchors adjustment 0; any weaker selection pays an Elo penalty proportional to
the log value ratio. Out-of-position picks are discounted before summing.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.config import (BAND_PREF, GK_MISMATCH, LINEUP_ELO_SCALE,
                          MAX_LINEUP_PENALTY, OOP_DEFAULT, OOP_DISCOUNT)
from util import band


def discount(bucket, pitch_band):
    if pitch_band == "GK" or bucket == "GK":
        return 1.0 if bucket == pitch_band == "GK" else GK_MISMATCH
    return OOP_DISCOUNT.get((bucket, pitch_band), OOP_DEFAULT)


def effective_value(player, slot):
    return (player["value_eur"] or 0.0) * discount(player["position"], band(slot))


def squad(conn, team):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM players WHERE team = ? ORDER BY value_eur DESC", (team,))]


def best_xi(conn, team, formation_slots):
    """Highest-value legal XI for the given slots (used as the Elo anchor).

    Band-by-band greedy: preferred bucket first by value, topping up from the
    best remaining players of any bucket if a bucket runs short.
    """
    players = squad(conn, team)
    used, xi = set(), []
    by_band = {}
    for slot in formation_slots:
        by_band.setdefault(band(slot), []).append(slot)
    for b in ("GK", "D", "F", "DM", "AM", "M"):  # scarcer buckets first
        slots = by_band.get(b, [])
        pref = BAND_PREF[b]
        pool = [p for p in players if p["id"] not in used and p["position"] == pref]
        for slot in slots:
            pick = pool.pop(0) if pool else max(
                (p for p in players if p["id"] not in used),
                key=lambda p: effective_value(p, slot), default=None)
            if pick is None:
                continue
            used.add(pick["id"])
            xi.append({"slot": slot, "player": pick})
    xi.sort(key=lambda e: formation_slots.index(e["slot"]) if e["slot"] in formation_slots else 99)
    total = sum(effective_value(e["player"], e["slot"]) for e in xi)
    return xi, total


def xi_quality(conn, team, entries):
    """entries: [{slot, player_id}] -> totals, per-band values, warnings."""
    ids = [e["player_id"] for e in entries]
    marks = ",".join("?" * len(ids))
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM players WHERE id IN ({marks})", ids)}
    total, per_band, detail, warnings = 0.0, {}, [], []
    for e in entries:
        p = rows.get(e["player_id"])
        if p is None or p["team"] != team:
            raise ValueError(f"player {e['player_id']} not in {team} squad")
        b = band(e["slot"])
        d = discount(p["position"], b)
        ev = (p["value_eur"] or 0.0) * d
        total += ev
        per_band[b] = per_band.get(b, 0.0) + ev
        detail.append({**p, "slot": e["slot"], "band": b, "eff_value": ev, "discount": d})
        if d <= GK_MISMATCH:
            warnings.append(f"{p['name']} ({p['position']}) in a {b} slot — massive downgrade")
        elif d <= 0.75:  # winger-ish FW<->AM/M-F pairings (0.85-0.9) are routine, not warnings
            warnings.append(f"{p['name']} ({p['position']}) out of position in a {b} slot")
        if p["status"] == "out":
            warnings.append(f"{p['name']} is flagged OUT ({p['status_note']}) but selected")
    return {"total": total, "per_band": per_band, "players": detail, "warnings": warnings}


def elo_adjustment(q_selected, q_best):
    if q_best <= 0 or q_selected <= 0:
        return MAX_LINEUP_PENALTY
    adj = LINEUP_ELO_SCALE * math.log(q_selected / q_best)
    return max(min(adj, 0.0), MAX_LINEUP_PENALTY)
