"""Player market values from Transfermarkt national-team squad pages.

One request per team (not per player). Players TM doesn't list get a heuristic
value from club tier x age curve x caps, recorded as value_source='heuristic'.
"""
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import CACHE_DIR, get_conn, get_meta
from util import norm

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Accept-Language": "en-US,en;q=0.9",
}

TM_TEAM_PAGES = {
    "England": "https://www.transfermarkt.com/england/startseite/verein/3299",
    "Norway": "https://www.transfermarkt.com/norwegen/startseite/verein/3440",
    "France": "https://www.transfermarkt.com/frankreich/startseite/verein/3377",
    "Spain": "https://www.transfermarkt.com/spanien/startseite/verein/3375",
    "Argentina": "https://www.transfermarkt.com/argentinien/startseite/verein/3437",
    "Switzerland": "https://www.transfermarkt.com/schweiz/startseite/verein/3384",
}

CLUB_TIERS = {
    60e6: ["Real Madrid", "Barcelona", "Manchester City", "Arsenal", "Liverpool",
           "Paris Saint-Germain", "Bayern Munich", "Chelsea"],
    35e6: ["Manchester United", "Tottenham Hotspur", "Newcastle United", "Atlético Madrid",
           "Juventus", "Inter Milan", "AC Milan", "Borussia Dortmund", "Bayer Leverkusen",
           "Napoli", "Aston Villa", "RB Leipzig", "Al Hilal"],
}
DEFAULT_CLUB_BASE = 12e6


def parse_value(text):
    m = re.search(r"€([\d.]+)\s*(m|k)", text.lower())
    if not m:
        return None
    return float(m.group(1)) * (1e6 if m.group(2) == "m" else 1e3)


def tm_values(url, cache_name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, cache_name)
    if not os.path.exists(cache):
        resp = requests.get(url, headers=UA, timeout=60)
        resp.raise_for_status()
        with open(cache, "w") as f:
            f.write(resp.text)
        time.sleep(2)
    soup = BeautifulSoup(open(cache).read(), "lxml")
    out = {}
    for row in soup.select("table.items > tbody > tr"):
        link = row.select_one("td.hauptlink a")
        val = row.select_one("td.rechts.hauptlink")
        if link and val:
            v = parse_value(val.get_text(" ", strip=True))
            if v:
                out[norm(link.get_text(strip=True))] = v
    return out


def age_mult(age):
    if age is None:
        return 0.8
    if age < 21:
        return 0.8
    if age <= 23:
        return 0.95
    if age <= 28:
        return 1.0
    if age <= 31:
        return 0.7
    if age <= 34:
        return 0.45
    return 0.25


def heuristic_value(p):
    base = DEFAULT_CLUB_BASE
    for tier_value, clubs in CLUB_TIERS.items():
        if p["club"] in clubs:
            base = tier_value
            break
    caps_mult = 0.7 + min(p["caps"] or 0, 80) / 80 * 0.6
    pos_mult = 0.6 if p["position"] == "GK" else 1.0
    return base * age_mult(p["age"]) * caps_mult * pos_mult


def run():
    conn = get_conn()
    teams = get_meta(conn, "remaining_teams") or list(TM_TEAM_PAGES)
    for team in teams:
        url = TM_TEAM_PAGES.get(team)
        values = {}
        if url:
            try:
                values = tm_values(url, f"tm_{team.lower()}.html")
            except requests.RequestException as e:
                print(f"!! {team}: transfermarkt fetch failed ({e}), using heuristic for all")
        players = conn.execute("SELECT * FROM players WHERE team = ?", (team,)).fetchall()
        hit = 0
        for p in players:
            key = norm(p["name"])
            v = values.get(key)
            if v is None:  # surname + first-initial fallback
                parts = key.split()
                cands = [tv for tk, tv in values.items()
                         if tk.split()[-1:] == parts[-1:] and tk[:1] == key[:1]]
                v = cands[0] if len(cands) == 1 else None
            if v is not None:
                hit += 1
                conn.execute("UPDATE players SET value_eur = ?, value_source = 'transfermarkt'"
                             " WHERE id = ?", (v, p["id"]))
            else:
                conn.execute("UPDATE players SET value_eur = ?, value_source = 'heuristic'"
                             " WHERE id = ?", (heuristic_value(dict(p)), p["id"]))
        print(f"{team}: {hit}/{len(players)} from transfermarkt, {len(players) - hit} heuristic")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    run()
