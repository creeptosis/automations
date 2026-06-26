# Dota 2 Replay Tool

A small **local** web GUI to search OpenDota and download Dota 2 replays straight
into your replay folder so they show up under **Watch → Downloaded**.

## Run

```
cd dota-replay-gui
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000**. (Or just double-click `run.bat` on Windows.)

## Three ways to find games

Hero fields are **type-to-search** (start typing "storm" and pick from the list).

| Tab mode | What it finds | Data source |
|---|---|---|
| **Notable players by hero** | Pro / notable players with the most games on a hero, ranked by win rate + recency. A **rank** column shows their current ladder rank (e.g. Immortal #2). Click **games ▾** to list and download that player's matches. Optional **Enemy mid** filter → only their mid games vs that hero. | `notable_players ⋈ player_matches ⋈ matches` + `/players` |
| **High-MMR by hero** | Recent top-bracket *public* games featuring a hero. Always **Immortal / top bracket** (no rank picker). Optional **Enemy hero** filter → only games where it was on the opposing team. | `public_matches` hero arrays, `avg_rank_tier = 75` |
| **Mid matchup** | Parsed games where two heroes were **both mid on opposing teams** (e.g. Storm Spirit vs Sniper). **hero A/B player** columns show each mid's name + ladder rank. | `player_matches` self-join on `lane_role = 2` + `/players` |
| **Raw SQL** | Anything the OpenDota explorer accepts. Any column named `match_id` becomes downloadable. | you decide |

Tick the matches you want and hit **Download selected** → watch progress on the
**Downloads** tab. Finished replays appear in **My Replays** (and in the Dota client).

### Matchup as a filter vs. the standalone tab

There are two ways to look at a matchup:
- The **Mid matchup** tab — the pure "Storm mid vs Sniper mid" explorer (parsed games, both confirmed mid).
- The **Enemy mid / Enemy hero** filter inside Notable and High-MMR — when you're already
  browsing a hero and want to narrow to a specific opponent. In Notable it's a true mid-vs-mid
  filter (`lane_role`); in High-MMR it's "enemy team has that hero" (public matches carry no lane data).

### Recent searches (left sidebar)

Every search is cached in your browser (`localStorage`, last 30). Click an entry in the left
sidebar to **instantly reload its results — no API call** — then **re-run live** if you want fresh
data. This is the main way to save OpenDota requests across sessions; it survives refreshes and
app restarts. Hit **×** to drop one, **clear all** to wipe.

### About ranks / MMR

Valve no longer publishes raw MMR, so exact numbers (e.g. "10k") aren't available
for anyone via OpenDota — `solo_competitive_rank` / `mmr_estimate` come back empty.
What *is* available and shown: **medal** (`rank_tier`) and, for Immortals, their
**leaderboard position** (`Immortal #2`). High-MMR public matches have anonymised
players, so only the **lobby average** rank is shown there; per-player ranks appear
in Matchup and Notable modes.

> **Why "Immortal" = avg rank 75:** `avg_rank_tier` is the *average* of all 10
> players, and OpenDota caps it at 75 in `public_matches` (verified: ≥76 returns
> zero rows). 75 is the Divine-5/Immortal matchmaking pool — the highest bracket
> the public data exposes. A literal all-Immortal average of 80 doesn't exist there.

## Why two different searches?

OpenDota stores data in two worlds:

- **Parsed matches** (`matches` / `player_matches`) have **lane info** (`lane_role`),
  which is what makes the *mid matchup* search possible — but they have **no clean
  MMR field**. The matchup query `LEFT JOIN`s `public_matches` so it can show the
  average rank when the game also happens to be a ranked public match (blank for pro games).
- **Public matches** (`public_matches` / `public_player_matches`) have an
  **average rank tier** (so *high-MMR by hero* works) but **no lane info**.

That's why "very high MMR" and "specific mid matchup" are separate modes.

## Config (optional environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DOTA_REPLAY_DIR` | `C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\dota\replays` | Where `.dem` files are saved (the folder the client actually reads). |
| `OPENDOTA_API_KEY` | _(none)_ | Higher OpenDota rate limits. Free tier works without it. |
| `DOTA_TZ` | `Asia/Singapore` | Timezone for the "played / last_played" columns (GMT+8). |

PowerShell example:
```powershell
$env:OPENDOTA_API_KEY = "your-key"; python app.py
```

## Notes & limits

- **Replays expire.** Valve keeps them ~2 weeks. If a replay is gone, OpenDota has
  no `replay_url`; the tool will ask OpenDota to *parse* the match and tell you to
  retry in a minute, but it cannot resurrect an expired replay.
- The free **explorer is rate-limited and has a query timeout**. The *High-MMR by
  hero* table is enormous — keep **months** and **limit** small (defaults 1 month / 50).
- Replays are `.dem.bz2`; the tool streams + decompresses to `.dem` on the fly.
- Hero IDs are fetched live from OpenDota and cached in `heroes_cache.json`.

## Hero IDs (handy)

Storm Spirit = **17**, Sniper = **35**. Full list comes from `/api/heroes` in the dropdowns.
