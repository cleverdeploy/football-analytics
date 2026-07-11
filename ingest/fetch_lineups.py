"""Scrape rotowire WC lineups: predicted/confirmed XI, slots, injury flags.

Source (user-provided): https://www.rotowire.com/soccer/lineups.php?league=WOC
Each lineup box = one fixture; each side lists 11 slot-coded players, then an
"Injuries" section with QUES/OUT/SUS tags. Full names live in a[title].
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import CACHE_DIR, get_conn, get_meta, set_meta
from util import band, norm

URL = "https://www.rotowire.com/soccer/lineups.php?league=WOC"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"}

STATUS_MAP = {"QUES": "doubtful", "OUT": "out", "SUS": "out", "INJ": "out"}


def formation_of(slots):
    counts = {}
    for s in slots:
        b = band(s)
        if b != "GK":
            counts[b] = counts.get(b, 0) + 1
    return "-".join(str(counts[b]) for b in ("D", "DM", "M", "AM", "F") if counts.get(b))


def fetch(force=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "rotowire.html")
    if force or not os.path.exists(cache):
        resp = requests.get(URL, headers=UA, timeout=60)
        resp.raise_for_status()
        with open(cache, "w") as f:
            f.write(resp.text)
    return cache


def parse_side(ul):
    """Return (xi, injuries): xi = [{slot, name}], injuries = [{name, status}]."""
    xi, injuries, in_injuries = [], [], False
    for li in ul.find_all("li"):
        classes = li.get("class") or []
        if "lineup__title" in classes:
            in_injuries = "injur" in li.get_text(strip=True).lower()
            continue
        if "lineup__player" not in classes:
            continue
        a = li.find("a")
        name = (a.get("title") if a else None) or li.get_text(" ", strip=True)
        text = li.get_text(" ", strip=True)
        m = re.search(r"\b(QUES|OUT|SUS|INJ)\b\s*$", text)
        tag = m.group(1) if m else None
        if in_injuries:
            if tag:
                injuries.append({"name": name, "status": STATUS_MAP[tag]})
        else:
            slot = text.split()[0]
            xi.append({"slot": slot, "name": name, "tag": tag})
    return xi, injuries


def match_player(conn, team, name):
    """Match a rotowire name to a players row; returns row or None."""
    target = norm(name)
    rows = conn.execute("SELECT id, name FROM players WHERE team = ?", (team,)).fetchall()
    for r in rows:
        if norm(r["name"]) == target:
            return r
    tparts = target.split()
    if not tparts:
        return None
    surname = tparts[-1]
    cands = [r for r in rows if norm(r["name"]).split()[-1:] == [surname]]
    if len(cands) == 1:
        return cands[0]
    # multi-word surnames ("Moller Wolfe") or middle names: containment either way
    cands = [r for r in rows if target in norm(r["name"]) or norm(r["name"]) in target]
    if len(cands) == 1:
        return cands[0]
    # last resort: same first initial + last token overlap
    cands = [r for r in rows
             if norm(r["name"])[0] == target[0] and surname in norm(r["name"]).split()]
    return cands[0] if len(cands) == 1 else None


def run(force=False):
    soup = BeautifulSoup(open(fetch(force)).read(), "lxml")
    conn = get_conn()
    seen_teams = []
    for box in soup.select("div.lineup.is-soccer"):
        teams = [x.get_text(strip=True) for x in box.select(".lineup__mteam")]
        if len(teams) != 2:
            continue
        for team, side in zip(teams, ("is-home", "is-visit")):
            ul = box.select_one(f"ul.lineup__list.{side}")
            if ul is None:
                continue
            known = conn.execute("SELECT 1 FROM players WHERE team = ?", (team,)).fetchone()
            if not known:
                print(f"!! {team}: no squad in DB, skipping")
                continue
            xi_raw, injuries = parse_side(ul)
            xi = []
            for entry in xi_raw:
                row = match_player(conn, team, entry["name"])
                if row is None:
                    print(f"!! {team}: unmatched XI player {entry['name']!r}")
                    continue
                xi.append({"slot": entry["slot"], "player_id": row["id"], "name": row["name"]})
                if entry["tag"]:
                    conn.execute("UPDATE players SET status = ?, status_note = ? WHERE id = ?",
                                 (STATUS_MAP[entry["tag"]], f"rotowire {entry['tag']}", row["id"]))
            for inj in injuries:
                row = match_player(conn, team, inj["name"])
                if row is None:
                    print(f"!! {team}: unmatched injury {inj['name']!r}")
                    continue
                conn.execute("UPDATE players SET status = ?, status_note = ? WHERE id = ?",
                             (inj["status"], "rotowire injuries list", row["id"]))
            formation = formation_of([e["slot"] for e in xi])
            conn.execute(
                "INSERT INTO lineups (team, formation, xi_json, source, fetched) VALUES (?,?,?,?,?)"
                " ON CONFLICT(team) DO UPDATE SET formation=excluded.formation,"
                " xi_json=excluded.xi_json, source=excluded.source, fetched=excluded.fetched",
                (team, formation, json.dumps(xi), "rotowire",
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            seen_teams.append(team)
            print(f"{team}: {formation}, XI {len(xi)}/11, injuries {len(injuries)}")
    if len(seen_teams) >= 4:
        set_meta(conn, "remaining_teams", sorted(set(seen_teams)))
    else:
        print("!! fewer than 4 teams found; keeping previous remaining_teams",
              get_meta(conn, "remaining_teams"))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    run(force="--force" in sys.argv)
