"""Football Analytics — WC 2026 match predictor. Flask API + static UI (port 8097)."""
import json
import os
import re
import sys

from flask import Flask, jsonify, redirect, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn, get_meta
from model.analysis import full_report
from model.config import FORMATIONS
from model.strength import best_xi
from util import band

app = Flask(__name__, static_folder="static", static_url_path="/static")

FLAGS = {"England": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
         "Norway": "🇳🇴", "France": "🇫🇷", "Spain": "🇪🇸",
         "Argentina": "🇦🇷", "Switzerland": "🇨🇭"}

APP_NAME = "Football Analytics"


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def team_slugs():
    conn = get_conn()
    names = get_meta(conn, "remaining_teams") or []
    conn.close()
    return {slugify(n): n for n in names}


def render_index(title):
    with open(os.path.join(app.static_folder, "index.html")) as f:
        return f.read().replace("<title>Football Analytics</title>",
                                f"<title>{title}</title>")


@app.route("/")
def index():
    return render_index(APP_NAME)


@app.route("/<slug>")
def match_permalink(slug):
    """Permalink like /england-vs-norway — serves the app with a matchup title."""
    m = re.fullmatch(r"([a-z0-9-]+)-vs-([a-z0-9-]+)", slug)
    if m:
        slugs = team_slugs()
        a, b = slugs.get(m.group(1)), slugs.get(m.group(2))
        if a and b and a != b:
            return render_index(f"{a} vs {b} — {APP_NAME}")
    return redirect("/")


@app.get("/api/teams")
def teams():
    conn = get_conn()
    names = get_meta(conn, "remaining_teams") or []
    out = []
    for name in names:
        r = conn.execute("SELECT rating FROM elo_ratings WHERE team = ?", (name,)).fetchone()
        rank = conn.execute("SELECT COUNT(*) + 1 FROM elo_ratings WHERE rating > ?",
                            (r["rating"],)).fetchone()[0]
        lu = conn.execute("SELECT formation, fetched FROM lineups WHERE team = ?", (name,)).fetchone()
        out.append({"name": name, "slug": slugify(name), "flag": FLAGS.get(name, "⚽"),
                    "rating": round(r["rating"]), "rank": rank,
                    "formation": lu["formation"] if lu else None,
                    "lineup_fetched": lu["fetched"] if lu else None})
    resp = {"teams": out, "formations": FORMATIONS,
            "results_through": conn.execute("SELECT MAX(date) FROM matches").fetchone()[0]}
    conn.close()
    return jsonify(resp)


@app.get("/api/team/<name>")
def team(name):
    conn = get_conn()
    players = [dict(r) for r in conn.execute(
        "SELECT id, name, position, shirt_no, age, caps, goals, club, value_eur,"
        " value_source, status, status_note FROM players WHERE team = ?"
        " ORDER BY CASE position WHEN 'GK' THEN 0 WHEN 'DF' THEN 1 WHEN 'MF' THEN 2"
        " ELSE 3 END, value_eur DESC", (name,))]
    if not players:
        conn.close()
        return jsonify({"error": f"unknown team {name!r}"}), 404
    lu = conn.execute("SELECT * FROM lineups WHERE team = ?", (name,)).fetchone()
    default = json.loads(lu["xi_json"]) if lu else []
    slots = [e["slot"] for e in default]
    bxi, _ = best_xi(conn, name, slots or FORMATIONS["4-2-3-1"])
    conn.close()
    return jsonify({"team": name, "flag": FLAGS.get(name, "⚽"), "players": players,
                    "default": {"formation": lu["formation"] if lu else "4-2-3-1",
                                "slots": slots, "xi": default,
                                "source": lu["source"] if lu else None,
                                "fetched": lu["fetched"] if lu else None},
                    "best_xi_ids": [e["player"]["id"] for e in bxi]})


@app.post("/api/predict")
def predict():
    body = request.get_json(force=True)
    mode = body.get("mode", "knockout")
    venue = body.get("venue", "neutral")
    sides = body.get("sides", [])
    if mode not in ("knockout", "group", "friendly") or venue not in ("neutral", "home_a", "home_b"):
        return jsonify({"error": "bad mode or venue"}), 400
    if len(sides) != 2 or sides[0]["team"] == sides[1]["team"]:
        return jsonify({"error": "need two different teams"}), 400
    for s in sides:
        xi = s.get("xi", [])
        if len(xi) != 11:
            return jsonify({"error": f"{s['team']}: XI must have 11 players, got {len(xi)}"}), 400
        if len({e["player_id"] for e in xi}) != 11:
            return jsonify({"error": f"{s['team']}: duplicate player in XI"}), 400
        if sum(1 for e in xi if band(e["slot"]) == "GK") != 1:
            return jsonify({"error": f"{s['team']}: exactly one GK slot required"}), 400
        s["slots"] = [e["slot"] for e in xi]
    conn = get_conn()
    try:
        report = full_report(conn, sides, mode=mode, venue=venue)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()
    report["mode"], report["venue"] = mode, venue
    return jsonify(report)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8097, debug=False)
