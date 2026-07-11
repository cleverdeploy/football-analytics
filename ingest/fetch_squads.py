"""Parse WC2026 squads (26 players/team) from Wikipedia for the remaining teams."""
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import CACHE_DIR, get_conn, set_meta

URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# Teams still alive as of 2026-07-11 (France/Spain in SF; ENG/NOR and ARG/SUI in today's QFs).
REMAINING = ["England", "Norway", "France", "Spain", "Argentina", "Switzerland"]


def fetch(force=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "squads.html")
    if force or not os.path.exists(cache):
        resp = requests.get(URL, headers=UA, timeout=60)
        resp.raise_for_status()
        with open(cache, "w") as f:
            f.write(resp.text)
    return cache


def parse_row(cells):
    pos = cells[1].get_text(" ", strip=True).split()[-1]  # "1 GK" -> "GK"
    name_cell = cells[2]
    name = name_cell.get_text(" ", strip=True)
    name = re.sub(r"\(\s*[^)]*\)", "", name)  # captain/vice-captain annotations
    name = re.sub(r"\s+", " ", name).strip()
    dob_text = cells[3].get_text(" ", strip=True)
    m = re.search(r"\(\s*(\d{4}-\d{2}-\d{2})\s*\)", dob_text)
    dob = m.group(1) if m else None
    m = re.search(r"aged?\s+(\d+)", dob_text)
    age = int(m.group(1)) if m else None
    caps = int(re.sub(r"\D", "", cells[4].get_text()) or 0)
    goals = int(re.sub(r"\D", "", cells[5].get_text()) or 0)
    club = cells[6].get_text(" ", strip=True)
    no = re.sub(r"\D", "", cells[0].get_text())
    return {
        "shirt_no": int(no) if no else None, "position": pos, "name": name,
        "dob": dob, "age": age, "caps": caps, "goals": goals, "club": club,
    }


def run(force=False):
    soup = BeautifulSoup(open(fetch(force)).read(), "lxml")
    conn = get_conn()
    for team in REMAINING:
        h3 = next((h for h in soup.find_all("h3") if h.get_text(strip=True) == team), None)
        if h3 is None:
            print(f"!! no section for {team}")
            continue
        table = h3.find_next("table", class_="wikitable")
        players = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 7:
                players.append(parse_row(cells))
        conn.execute("DELETE FROM players WHERE team = ?", (team,))
        conn.executemany(
            "INSERT INTO players (team, name, position, shirt_no, dob, age, caps, goals, club)"
            " VALUES (:team, :name, :position, :shirt_no, :dob, :age, :caps, :goals, :club)",
            [{**p, "team": team} for p in players],
        )
        gk = sum(1 for p in players if p["position"] == "GK")
        print(f"{team}: {len(players)} players ({gk} GK)")
    set_meta(conn, "remaining_teams", REMAINING)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    run(force="--force" in sys.argv)
