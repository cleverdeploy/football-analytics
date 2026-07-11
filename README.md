# WC 2026 Match Predictor

Pick any two teams still in the 2026 World Cup, edit either starting XI on a pitch view,
and get a win probability with a full data-backed justification — Elo baseline, form,
head-to-head, per-band lineup values, named absentees, and the highest-impact substitutions.

Built on QF day (11 Jul 2026, Norway v England) — defaults to that fixture.

**Live: https://football.wasim.dev**

## Run

```bash
python3 app.py            # http://localhost:8097  (0.0.0.0, port 8097)
```

## Deploy

Push to `main` → Dokploy auto-deploys (`football` project / `football-web` app at
dokploy.cleverdeploy.com; **Build Type must stay "Dockerfile"**, container port 8000).
Repo: github.com/cleverdeploy/football-analytics (public — Dokploy pulls via plain Git).
DNS: Cloudflare A record `football.wasim.dev → 178.104.246.72`, DNS-only/grey cloud.
The image ships `data/football.db`, so refresh data locally (`python3 ingest/run_all.py --force`),
commit the DB, and push to update the live site.

## Refresh data

```bash
python3 ingest/run_all.py           # uses cached pages where present
python3 ingest/run_all.py --force   # refetch results CSV, Wikipedia squads, rotowire lineups
# (Transfermarkt pages cache in data/cache/tm_*.html — delete to refetch)
```

Pipeline: results (martj42 CSV, 1872→present) → Elo (importance-weighted K, goal-diff
multiplier, +100 home) → squads (Wikipedia WC2026 squad tables) → lineups + injury flags
(rotowire, also defines the "remaining teams" set) → market values (Transfermarkt
national-team pages, heuristic fallback) → refit Elo→goals map.

## Model

1. **Team baseline** — Elo computed from all 49k+ internationals; each match also stores
   pre-match ratings.
2. **Lineup adjustment** — `150 × ln(XI value / best-XI value)` Elo points, with
   out-of-position discounts (outfielder in goal ≈ 15% of value). Full strength = 0;
   weaker picks only cost.
3. **Outcome** — adjusted Elo diff → expected goals via `log λ = a + b·Δelo` fitted on
   the historical matches (both perspectives), then an independent Poisson grid gives
   win/draw/loss + scorelines. Knockout draws resolve via extra time (rates × ⅓) and
   50/50 penalties into a single advance %.
4. **Analysis** — deterministic template prose over the factor breakdown; every claim
   traces to a number in the section data (JSON in `/api/predict`).

Constants live in `model/config.py`.

## Tests

```bash
python3 tests/test_model.py    # 20 sanity checks (symmetry, monotonicity, Haaland tests)
python3 test_playwright.py     # smoke: renders, swap Haaland, % moves (server must be up)
```

## Structure

```
app.py                  Flask API + static serving (port 8097)
db.py / util.py         SQLite schema+helpers / name+slot normalisation
ingest/                 fetch_results, compute_elo, fetch_squads, fetch_lineups,
                        fetch_values, run_all
model/                  config (constants), strength (lineup→Elo), predict
                        (Elo→Poisson), analysis (report + prose)
static/                 index.html, app.js (vanilla JS + hand-built SVG charts), style.css
data/football.db        all tables; data/cache/ raw fetches
```

## API

- `GET /api/teams` — remaining teams, ratings, formation presets
- `GET /api/team/<name>` — squad with values/status, rotowire default XI, best-XI ids
- `POST /api/predict` — `{mode, venue, sides:[{team, xi:[{slot, player_id}]}]}` →
  probabilities + adjustments + 8 analysis sections
