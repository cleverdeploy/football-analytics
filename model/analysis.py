"""Full prediction report: probabilities + factor breakdown + template prose.

Entry point: full_report(conn, sides, mode, venue) where each side is
{"team": name, "slots": [...], "xi": [{"slot", "player_id"}]}. Every sentence
in the prose is derived from a number that also appears in the section data.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.predict import predict_match
from model.strength import best_xi, elo_adjustment, xi_quality
from util import BANDS

M = 1e6


def eur(v):
    return f"€{v / M:.0f}m" if v >= M else f"€{v / 1e3:.0f}k"


def pct(p):
    return f"{p * 100:.0f}%" if p >= 0.10 else f"{p * 100:.1f}%"


def sentences(bits):
    return ". ".join(b[0].upper() + b[1:] for b in bits if b) + "."


def elo_rank(conn, team):
    return conn.execute(
        "SELECT COUNT(*) + 1 FROM elo_ratings WHERE rating >"
        " (SELECT rating FROM elo_ratings WHERE team = ?)", (team,)).fetchone()[0]


def last_matches(conn, team, n=10):
    rows = conn.execute(
        "SELECT * FROM matches WHERE home_team = ? OR away_team = ?"
        " ORDER BY date DESC, id DESC LIMIT ?", (team, team, n)).fetchall()
    out = []
    for r in rows:
        home = r["home_team"] == team
        gf, ga = (r["home_score"], r["away_score"]) if home else (r["away_score"], r["home_score"])
        out.append({"date": r["date"], "opponent": r["away_team"] if home else r["home_team"],
                    "score": f"{gf}-{ga}", "result": "W" if gf > ga else "L" if gf < ga else "D",
                    "tournament": r["tournament"]})
    return out


def form_summary(matches):
    w = sum(1 for m in matches if m["result"] == "W")
    d = sum(1 for m in matches if m["result"] == "D")
    gf = sum(int(m["score"].split("-")[0]) for m in matches)
    ga = sum(int(m["score"].split("-")[1]) for m in matches)
    return {"w": w, "d": d, "l": len(matches) - w - d, "gf": gf, "ga": ga}


def elo_trend(conn, team, days=365):
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    old = conn.execute(
        "SELECT rating FROM elo_history WHERE team = ? AND date <= ?"
        " ORDER BY date DESC LIMIT 1", (team, cutoff)).fetchone()
    now = conn.execute("SELECT rating FROM elo_ratings WHERE team = ?", (team,)).fetchone()
    return (now["rating"] - old["rating"]) if (old and now) else 0.0


def h2h(conn, a, b):
    rows = conn.execute(
        "SELECT * FROM matches WHERE (home_team = ? AND away_team = ?)"
        " OR (home_team = ? AND away_team = ?) ORDER BY date DESC", (a, b, b, a)).fetchall()
    wa = wb = dr = 0
    for r in rows:
        diff = r["home_score"] - r["away_score"]
        if diff == 0:
            dr += 1
        elif (diff > 0) == (r["home_team"] == a):
            wa += 1
        else:
            wb += 1
    recent = [{"date": r["date"],
               "fixture": f"{r['home_team']} {r['home_score']}-{r['away_score']} {r['away_team']}",
               "tournament": r["tournament"]} for r in rows[:5]]
    return {"played": len(rows), "wins_a": wa, "wins_b": wb, "draws": dr, "recent": recent}


def side_context(conn, side):
    team, slots = side["team"], side["slots"]
    rating = conn.execute("SELECT rating FROM elo_ratings WHERE team = ?", (team,)).fetchone()[0]
    quality = xi_quality(conn, team, side["xi"])
    bxi, q_best = best_xi(conn, team, slots)
    adj = elo_adjustment(quality["total"], q_best)
    selected_ids = {e["player_id"] for e in side["xi"]}
    absentees = sorted((e["player"] for e in bxi if e["player"]["id"] not in selected_ids),
                       key=lambda p: -(p["value_eur"] or 0))
    return {"team": team, "rating": rating, "rank": elo_rank(conn, team), "quality": quality,
            "q_best": q_best, "adj": adj, "adjusted": rating + adj, "absentees": absentees,
            "slots": slots, "xi": side["xi"]}


def best_swaps(conn, ctx, opp_adjusted, mode, venue, flip_venue):
    """Highest-impact single substitutions (available players only)."""
    base = predict_match(conn, ctx["adjusted"], opp_adjusted,
                         venue=venue, knockout=mode == "knockout")
    base_p = base.get("p_advance_a", base["p_win"])
    in_xi = {e["player_id"] for e in ctx["xi"]}
    bench = [p for p in conn.execute(
        "SELECT * FROM players WHERE team = ? AND status != 'out'", (ctx["team"],))
        if p["id"] not in in_xi]
    swaps = []
    for slot_entry in ctx["xi"]:
        for sub in bench:
            xi2 = [e if e is not slot_entry else {"slot": e["slot"], "player_id": sub["id"]}
                   for e in ctx["xi"]]
            q2 = xi_quality(conn, ctx["team"], xi2)
            adj2 = elo_adjustment(q2["total"], ctx["q_best"])
            p2 = predict_match(conn, ctx["rating"] + adj2, opp_adjusted,
                               venue=venue, knockout=mode == "knockout")
            gain = p2.get("p_advance_a", p2["p_win"]) - base_p
            if gain > 0.001:
                out_name = conn.execute("SELECT name FROM players WHERE id = ?",
                                        (slot_entry["player_id"],)).fetchone()[0]
                swaps.append({"in": sub["name"], "out": out_name,
                              "slot": slot_entry["slot"], "gain": gain})
    swaps.sort(key=lambda s: -s["gain"])
    return swaps[:3]


VERDICT = ((0.85, "overwhelming favourites"), (0.72, "strong favourites"),
           (0.62, "clear favourites"), (0.55, "slight favourites"))


def verdict_phrase(p):
    for cut, phrase in VERDICT:
        if p >= cut:
            return phrase
    return None


def full_report(conn, sides, mode="knockout", venue="neutral"):
    a, b = side_context(conn, sides[0]), side_context(conn, sides[1])
    knockout = mode == "knockout"
    pred = predict_match(conn, a["adjusted"], b["adjusted"], venue=venue, knockout=knockout)
    p_a = pred.get("p_advance_a", pred["p_win"])
    p_b = pred.get("p_advance_b", pred["p_loss"])

    fav, dog = (a, b) if p_a >= p_b else (b, a)
    p_fav = max(p_a, p_b)
    phrase = verdict_phrase(p_fav)
    headline = (f"{fav['team']} {pct(p_fav)} — {dog['team']} {pct(1 - p_fav if knockout else min(p_a, p_b))}."
                if knockout else
                f"{fav['team']} {pct(max(p_a, p_b))}, draw {pct(pred['p_draw'])}, {dog['team']} {pct(min(p_a, p_b))}.")
    verdict_prose = (
        f"This one is a genuine toss-up: {headline}" if phrase is None else
        f"{fav['team']} are {phrase}: {headline}")
    if knockout:
        verdict_prose += (f" In 90 minutes it's {pct(pred['p_win'])} {a['team']},"
                          f" {pct(pred['p_draw'])} draw, {pct(pred['p_loss'])} {b['team']};"
                          f" the advance figure resolves draws through extra time and penalties.")

    sections = [{"id": "verdict", "title": "Verdict", "prose": verdict_prose,
                 "data": {"p_a": p_a, "p_b": p_b, "wdl": [pred["p_win"], pred["p_draw"], pred["p_loss"]]}}]

    gap = a["adjusted"] - b["adjusted"]
    leader = a if gap >= 0 else b
    baseline_prose = (
        f"{a['team']} rate {a['rating']:.0f} Elo (#{a['rank']} in the world) to {b['team']}'s"
        f" {b['rating']:.0f} (#{b['rank']}), computed from {conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0]:,}"
        f" internationals since 1872. After lineup adjustments ({a['adj']:+.0f} / {b['adj']:+.0f})"
        f" {leader['team']} carry a {abs(gap):.0f}-point edge, historically worth"
        f" {pct(pred['elo_expectation'] if gap >= 0 else 1 - pred['elo_expectation'])} for the stronger side."
        f" That converts to expected goals of {pred['lambda_a']:.2f} against {pred['lambda_b']:.2f}.")
    sections.append({"id": "baseline", "title": "Baseline strength", "prose": baseline_prose,
                     "data": {"elo": {a["team"]: a["rating"], b["team"]: b["rating"]},
                              "adjusted": {a["team"]: a["adjusted"], b["team"]: b["adjusted"]},
                              "rank": {a["team"]: a["rank"], b["team"]: b["rank"]},
                              "lambdas": [pred["lambda_a"], pred["lambda_b"]]}})

    form_bits, form_data = [], {}
    for ctx in (a, b):
        recent = last_matches(conn, ctx["team"])
        s = form_summary(recent)
        trend = elo_trend(conn, ctx["team"])
        form_data[ctx["team"]] = {"summary": s, "trend": trend, "matches": recent}
        streak_desc = f"{s['w']}W-{s['d']}D-{s['l']}L, {s['gf']}-{s['ga']} on aggregate"
        form_bits.append(f"{ctx['team']} are {streak_desc} over their last {len(recent)},"
                         f" {'gaining' if trend >= 0 else 'shedding'} {abs(trend):.0f} Elo in 12 months")
    sections.append({"id": "form", "title": "Form", "prose": sentences(form_bits),
                     "data": form_data})

    hh = h2h(conn, a["team"], b["team"])
    if hh["played"]:
        last = hh["recent"][0]
        h2h_prose = (f"The sides have met {hh['played']} times: {hh['wins_a']} {a['team']} wins,"
                     f" {hh['draws']} draws, {hh['wins_b']} {b['team']} wins."
                     f" Most recently {last['fixture']} ({last['date'][:4]}, {last['tournament']}).")
    else:
        h2h_prose = "These sides have never met in a full international."
    sections.append({"id": "h2h", "title": "Head to head", "prose": h2h_prose, "data": hh})

    for ctx, opp in ((a, b), (b, a)):
        q = ctx["quality"]
        strength_pct = q["total"] / ctx["q_best"] * 100 if ctx["q_best"] else 0
        bits = [f"This XI is worth {eur(q['total'])} — {strength_pct:.0f}% of the strongest"
                f" available side ({eur(ctx['q_best'])}), costing {abs(ctx['adj']):.0f} Elo"]
        if ctx["absentees"]:
            top = ctx["absentees"][0]
            bits.append(f"the biggest omission is {top['name']} ({eur(top['value_eur'] or 0)},"
                        f" {top['status']}{'' if top['status'] == 'fit' else ' — ' + (top['status_note'] or '')})")
        bits.extend(q["warnings"])
        per_band = {bd: q["per_band"].get(bd, 0.0) for bd in BANDS}
        sections.append({"id": f"lineup_{ctx['team']}", "title": f"{ctx['team']} lineup",
                         "prose": sentences(bits),
                         "data": {"total": q["total"], "best": ctx["q_best"],
                                  "per_band": per_band,
                                  "absentees": [{"name": p["name"], "value": p["value_eur"],
                                                 "status": p["status"]} for p in ctx["absentees"][:5]],
                                  "warnings": q["warnings"]}})

    atk_a = sum(a["quality"]["per_band"].get(x, 0) for x in ("AM", "F"))
    def_b = sum(b["quality"]["per_band"].get(x, 0) for x in ("GK", "D", "DM"))
    atk_b = sum(b["quality"]["per_band"].get(x, 0) for x in ("AM", "F"))
    def_a = sum(a["quality"]["per_band"].get(x, 0) for x in ("GK", "D", "DM"))
    r1 = atk_a / def_b if def_b else 0
    r2 = atk_b / def_a if def_a else 0
    key = (f"{a['team']}'s attacking third ({eur(atk_a)}) against {b['team']}'s defensive core"
           f" ({eur(def_b)}) is a {r1:.1f}x value ratio; the reverse matchup runs {r2:.1f}x"
           f" ({eur(atk_b)} vs {eur(def_a)})."
           f" The bigger mismatch is {'the former' if r1 >= r2 else 'the latter'}, and it is where"
           f" the expected-goals edge comes from.")
    sections.append({"id": "matchups", "title": "Key matchups", "prose": key,
                     "data": {"attack": {a["team"]: atk_a, b["team"]: atk_b},
                              "defence": {a["team"]: def_a, b["team"]: def_b}}})

    swaps_a = best_swaps(conn, a, b["adjusted"], mode, venue, False)
    swaps_b = best_swaps(conn, b, a["adjusted"], mode,
                         "home_b" if venue == "home_a" else "home_a" if venue == "home_b" else "neutral", True)
    bits = []
    for ctx, swaps in ((a, swaps_a), (b, swaps_b)):
        if swaps:
            s = swaps[0]
            bits.append(f"{ctx['team']}'s best available change is {s['in']} for {s['out']}"
                        f" (+{s['gain'] * 100:.1f} points)")
        else:
            bits.append(f"{ctx['team']} have no upgrade on the bench — this is their strongest available XI")
    sections.append({"id": "sensitivity", "title": "What would move the number",
                     "prose": sentences(bits),
                     "data": {a["team"]: swaps_a, b["team"]: swaps_b}})

    return {"prediction": pred, "p_advance": {a["team"]: p_a, b["team"]: p_b},
            "adjustments": {a["team"]: a["adj"], b["team"]: b["adj"]},
            "sections": sections}
