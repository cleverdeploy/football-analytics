"""Model sanity checks (plain asserts). Run: python3 tests/test_model.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_conn
from model.analysis import full_report
from model.predict import predict_match
from model.strength import best_xi, elo_adjustment, xi_quality

conn = get_conn()
checks = 0


def ok(cond, label):
    global checks
    assert cond, f"FAIL: {label}"
    checks += 1
    print(f"  ok - {label}")


def side_for(team):
    xi = json.loads(conn.execute("SELECT xi_json FROM lineups WHERE team=?", (team,)).fetchone()[0])
    return {"team": team, "slots": [e["slot"] for e in xi],
            "xi": [{"slot": e["slot"], "player_id": e["player_id"]} for e in xi]}


print("elo -> outcome")
p_even = predict_match(conn, 1900, 1900)
ok(abs(p_even["p_win"] - p_even["p_loss"]) < 1e-9, "even teams are symmetric")
ok(abs(p_even["p_advance_a"] - 0.5) < 1e-9, "even knockout is 50/50")
prev = 0
for gap in (0, 50, 100, 200, 400):
    p = predict_match(conn, 1900 + gap, 1900)
    ok(p["p_advance_a"] >= prev, f"advance monotonic at +{gap}")
    prev = p["p_advance_a"]
p_home = predict_match(conn, 1900, 1900, venue="home_a")
ok(p_home["p_win"] > p_home["p_loss"], "home advantage helps")

print("lineups")
eng, nor = side_for("England"), side_for("Norway")
rep = full_report(conn, [eng, nor])
p_eng = rep["p_advance"]["England"]
ok(0.30 < p_eng < 0.70, f"England v Norway in plausible band ({p_eng:.2f})")
ok(rep["adjustments"]["England"] <= 0 and rep["adjustments"]["Norway"] <= 0,
   "lineup adjustments never exceed full strength")
ok(len(rep["sections"]) == 8, "eight analysis sections")
ok(all(s["prose"] for s in rep["sections"]), "every section has prose")

haaland = conn.execute("SELECT id FROM players WHERE name LIKE '%Haaland%'").fetchone()[0]
larsen = conn.execute("SELECT id FROM players WHERE name LIKE '%Strand Larsen%'").fetchone()[0]
nor2 = {**nor, "xi": [e if e["player_id"] != haaland else {**e, "player_id": larsen}
                      for e in nor["xi"]]}
rep2 = full_report(conn, [eng, nor2])
drop = rep["p_advance"]["Norway"] - rep2["p_advance"]["Norway"]
ok(drop > 0.03, f"benching Haaland costs Norway >3 points ({drop * 100:.1f})")

gk_slot = next(e for e in nor["xi"] if e["slot"] == "GK")
nor3 = {**nor, "xi": [e if e["slot"] != "GK" else {**e, "player_id": haaland} for e in nor["xi"]
                      ]}
nor3["xi"] = [e if e["player_id"] != haaland or e["slot"] == "GK"
              else {**e, "player_id": gk_slot["player_id"]} for e in nor3["xi"]]
q3 = xi_quality(conn, "Norway", nor3["xi"])
ok(any("massive downgrade" in w for w in q3["warnings"]), "outfielder in goal warns")
rep3 = full_report(conn, [eng, nor3])
ok(rep["p_advance"]["Norway"] - rep3["p_advance"]["Norway"] > 0.05,
   "Haaland in goal tanks Norway by >5 points")

try:
    xi_quality(conn, "England", nor["xi"])
    ok(False, "wrong-team XI rejected")
except ValueError:
    ok(True, "wrong-team XI rejected")

slots = [e["slot"] for e in nor["xi"]]
bxi, q_best = best_xi(conn, "Norway", slots)
ok(len(bxi) == 11, "best XI has 11 players")
ok(len({e["player"]["id"] for e in bxi}) == 11, "best XI has no duplicates")
q_def = xi_quality(conn, "Norway", nor["xi"])["total"]
ok(q_best >= q_def, "best XI >= default XI value")
ok(elo_adjustment(q_best, q_best) == 0, "full-strength adjustment is zero")

print(f"\nall {checks} checks passed")
conn.close()
