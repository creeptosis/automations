#!/usr/bin/env python3
"""
Local web GUI for searching OpenDota and downloading Dota 2 replays.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000 in your browser.

What it does
------------
- Search OpenDota's SQL "explorer" for:
    * Notable players by hero (win rate + recency)   -> drill into their games
    * High-MMR public games by hero (avg_rank_tier)
    * Mid-lane matchups (e.g. Storm Spirit mid vs Sniper mid)
    * Raw SQL (power user)
- Pick matches and download their replays straight into your Dota 2 replays
  folder, decompressed to .dem so they appear under Watch -> Downloaded.
- Browse the replays already in your folder.

Notes
-----
- Valve only keeps replays for ~2 weeks. Expired = unrecoverable.
- The free OpenDota explorer is rate-limited and has a statement timeout;
  keep "months" and "limit" modest. Set OPENDOTA_API_KEY for higher limits.
"""

import base64
import bz2
import json
import os
import queue
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from flask import Flask, jsonify, request, send_from_directory

import replay_titles  # local: reads/writes Dota's downloaded_replays_info.dat (custom names)

# ---------------------------------------------------------------------------
# CONFIG (override via environment variables)
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))

# The folder the Dota 2 client actually reads (note the extra \dota).
DEFAULT_REPLAY_DIR = (
    r"C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\dota\replays"
)
REPLAY_DIR = os.environ.get("DOTA_REPLAY_DIR", DEFAULT_REPLAY_DIR)

OPENDOTA = "https://api.opendota.com/api"
API_KEY = os.environ.get("OPENDOTA_API_KEY", "").strip()
TZ = os.environ.get("DOTA_TZ", "Asia/Singapore")  # GMT+8, matches your query
HEROES_CACHE = os.path.join(HERE, "heroes_cache.json")
# Files on disk stay named {match_id}.dem so the Dota client's Downloaded list works;
# this maps match_id -> descriptive label, shown in the app's My Replays tab.
REPLAY_NAMES = os.path.join(HERE, "replay_names.json")
DOWNLOAD_WORKERS = 1  # sequential = polite to Valve and clearer progress

app = Flask(__name__, static_folder="static", static_url_path="")
app.json.sort_keys = False  # preserve our result column order in JSON responses


# ---------------------------------------------------------------------------
# OpenDota helpers
# ---------------------------------------------------------------------------
def _params(extra=None):
    p = dict(extra or {})
    if API_KEY:
        p["api_key"] = API_KEY
    return p


def explorer(sql, _retries=2):
    """Run SQL against OpenDota's explorer; return list of row dicts.

    The free explorer is flaky: it returns transient "Query read timeout" JSON
    errors and, when Cloudflare can't reach the origin, non-JSON 5xx pages
    (e.g. 522). Retry those a few times with backoff before giving up.
    """
    last_err = None
    for attempt in range(_retries + 1):
        transient = False
        try:
            r = requests.get(f"{OPENDOTA}/explorer", params=_params({"sql": sql}), timeout=120)
        except requests.RequestException as e:
            last_err, transient = f"request failed: {e}", True
        else:
            try:
                j = r.json()
            except ValueError:
                last_err = f"OpenDota returned non-JSON ({r.status_code}): {r.text[:200]}"
                transient = r.status_code >= 500 or r.status_code == 429
            else:
                if r.status_code == 200 and not j.get("err"):
                    return j.get("rows", [])
                last_err = j.get("err") or j.get("error") or f"HTTP {r.status_code}: {r.text[:200]}"
                transient = ("timeout" in str(last_err).lower()
                             or r.status_code >= 500 or r.status_code == 429)
        if not transient or attempt == _retries:
            break
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_err or "OpenDota explorer failed")


def get_heroes(force=False):
    """Hero list [{id, name}], cached to disk so we don't refetch each load."""
    if not force and os.path.exists(HEROES_CACHE):
        try:
            with open(HEROES_CACHE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    r = requests.get(f"{OPENDOTA}/heroes", params=_params(), timeout=30)
    r.raise_for_status()
    heroes = [{"id": h["id"], "name": h["localized_name"]} for h in r.json()]
    heroes.sort(key=lambda h: h["name"])
    try:
        with open(HEROES_CACHE, "w", encoding="utf-8") as f:
            json.dump(heroes, f)
    except OSError:
        pass
    return heroes


def _int(v, default, lo, hi):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


# ---------------------------------------------------------------------------
# Player rank lookup.  Valve no longer publishes raw MMR (solo_competitive_rank
# etc. are null), so the best available signal is rank_tier (medal) plus
# leaderboard_rank for Immortals.  Cached per process; ranks change slowly.
# ---------------------------------------------------------------------------
MEDALS = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
          5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal"}
_rank_cache = {}
_rank_lock = threading.Lock()


def fmt_rank(rank_tier, leaderboard_rank):
    if not rank_tier:
        return None
    medal, stars = rank_tier // 10, rank_tier % 10
    name = MEDALS.get(medal, str(rank_tier))
    if medal >= 8:  # Immortal — show ladder position when available
        return f"Immortal #{leaderboard_rank}" if leaderboard_rank else "Immortal"
    return f"{name} {stars}" if stars else name


def get_player(account_id):
    with _rank_lock:
        if account_id in _rank_cache:
            return _rank_cache[account_id]
    info = {"rank": None, "name": None, "rank_tier": None, "leaderboard_rank": None}
    try:
        r = requests.get(f"{OPENDOTA}/players/{account_id}", params=_params(), timeout=20)
        if r.status_code == 200:
            p = r.json()
            prof = p.get("profile") or {}
            # Pros often set junk Steam personas ("a", "))"); their real handle lives
            # in profile.name (e.g. "RCY", "TaiLung"). Prefer it, fall back to persona.
            info = {
                "rank": fmt_rank(p.get("rank_tier"), p.get("leaderboard_rank")),
                "name": prof.get("name") or prof.get("personaname"),
                "rank_tier": p.get("rank_tier"),
                "leaderboard_rank": p.get("leaderboard_rank"),
            }
    except requests.RequestException:
        pass
    with _rank_lock:
        _rank_cache[account_id] = info
    return info


def enrich_players(account_ids):
    ids = list(dict.fromkeys(int(a) for a in account_ids if a))
    missing = [a for a in ids if a not in _rank_cache]
    if missing:
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(get_player, missing))
    blank = {"rank": None, "name": None, "rank_tier": None, "leaderboard_rank": None}
    with _rank_lock:
        return {a: _rank_cache.get(a, blank) for a in ids}


def _player_str(info):
    name, rank = (info or {}).get("name"), (info or {}).get("rank")
    if rank and name:
        return f"{name} · {rank}"
    return rank or name or "—"


def enrich_rows(mode, rows):
    """Add player rank/leaderboard columns to search results where possible."""
    if not rows:
        return rows
    if mode == "matchup":
        info = enrich_players([r.get("a_account") for r in rows] +
                              [r.get("b_account") for r in rows])

        def side(acc):
            i = info.get(acc or 0) or {}
            return {"name": i.get("name"), "rank": i.get("rank"),
                    "rank_tier": i.get("rank_tier"),
                    "leaderboard_rank": i.get("leaderboard_rank")}

        out = []
        for r in rows:
            out.append({
                "match_id": r.get("match_id"),
                "played": r.get("played"),
                "a_win": r.get("a_win"),
                "a": side(r.get("a_account")),
                "b": side(r.get("b_account")),
                "avg_rank_tier": r.get("avg_rank_tier"),
                "duration": r.get("duration"),
            })
        return out
    return rows


# ---------------------------------------------------------------------------
# SQL builders.  All user input is coerced to validated ints, so the f-strings
# below are injection-safe (no free text reaches the SQL except in raw mode).
# ---------------------------------------------------------------------------
def _enemy_join(vs_hero, vs_lane=0):
    """Optional JOIN restricting a player_matches row (alias pm) to games where an
    opponent played vs_hero — optionally in a specific lane (lane_role: 1 safe,
    2 mid, 3 off, 4 jungle; 0 = any lane). The searched hero's own lane is left
    unconstrained, so this is "faced this enemy", not "both in this lane"."""
    if not vs_hero:
        return ""
    lane = f"AND opp.lane_role = {vs_lane}" if vs_lane else ""
    return (f"JOIN player_matches opp ON opp.match_id = pm.match_id\n"
            f"  AND opp.hero_id = {vs_hero} {lane}\n"
            f"  AND (pm.player_slot < 128) <> (opp.player_slot < 128)")


def sql_notable(hero, months, min_games, limit, vs_hero=0, vs_lane=0):
    join = _enemy_join(vs_hero, vs_lane)
    return f"""
SELECT np.name, np.team_name, pm.account_id,
  COUNT(*) AS hero_games,
  SUM(CASE WHEN (pm.player_slot < 128) = m.radiant_win THEN 1 ELSE 0 END) AS wins,
  CAST(100.0 * SUM(CASE WHEN (pm.player_slot < 128) = m.radiant_win THEN 1 ELSE 0 END)
       / COUNT(*) AS INTEGER) AS wr_pct,
  to_char(to_timestamp(MAX(m.start_time)) AT TIME ZONE '{TZ}', 'YYYY-MM-DD HH24:MI') AS last_played
FROM notable_players np
JOIN player_matches pm ON pm.account_id = np.account_id
JOIN matches m ON m.match_id = pm.match_id
{join}
WHERE pm.hero_id = {hero}
  AND m.start_time > extract(epoch FROM now() - interval '{months} months')
GROUP BY np.name, np.team_name, pm.account_id
HAVING COUNT(*) >= {min_games}
ORDER BY wr_pct DESC, hero_games DESC
LIMIT {limit}
"""


def sql_notable_games(account_ids, hero, months, vs_hero=0, vs_lane=0):
    """Individual games behind the notable aggregate, for the given accounts, so the
    UI can list each player's matches inline with download checkboxes. When an enemy
    hero is set, also return the lane that enemy played in each game (enemy_lane)."""
    join = _enemy_join(vs_hero, vs_lane)
    enemy_lane = "opp.lane_role AS enemy_lane" if vs_hero else "NULL AS enemy_lane"
    ids = ",".join(str(int(a)) for a in account_ids)
    return f"""
SELECT pm.account_id, m.match_id,
  to_char(to_timestamp(m.start_time) AT TIME ZONE '{TZ}', 'YYYY-MM-DD HH24:MI') AS played,
  (pm.player_slot < 128) = m.radiant_win AS won,
  m.duration,
  {enemy_lane}
FROM player_matches pm
JOIN matches m ON m.match_id = pm.match_id
{join}
WHERE pm.account_id IN ({ids}) AND pm.hero_id = {hero}
  AND m.start_time > extract(epoch FROM now() - interval '{months} months')
ORDER BY pm.account_id, m.start_time DESC
LIMIT 3000
"""


def sql_matchup(hero_a, hero_b, months, limit, require_mid, min_tier):
    mid_a = "AND a.lane_role = 2" if require_mid else ""
    mid_b = "AND b.lane_role = 2" if require_mid else ""
    # public_matches.avg_rank_tier tops out at 75 (Divine 5), and pro/parsed/league
    # games aren't in public_matches at all (NULL). Keep high-rank pubs AND those
    # NULL-avg games (they're the top pro matches), dropping only explicitly-low pubs.
    tier = f"AND (pubm.avg_rank_tier >= {min_tier} OR pubm.avg_rank_tier IS NULL)" if min_tier else ""
    return f"""
SELECT m.match_id,
  pubm.avg_rank_tier,
  to_char(to_timestamp(m.start_time) AT TIME ZONE '{TZ}', 'YYYY-MM-DD HH24:MI') AS played,
  (a.player_slot < 128) = m.radiant_win AS a_win,
  m.duration,
  a.account_id AS a_account,
  b.account_id AS b_account
FROM player_matches a
JOIN player_matches b ON b.match_id = a.match_id
JOIN matches m ON m.match_id = a.match_id
LEFT JOIN public_matches pubm ON pubm.match_id = m.match_id
WHERE a.hero_id = {hero_a} {mid_a}
  AND b.hero_id = {hero_b} {mid_b}
  AND (a.player_slot < 128) <> (b.player_slot < 128)
  AND m.start_time > extract(epoch FROM now() - interval '{months} months')
  {tier}
ORDER BY m.start_time DESC
LIMIT {limit}
"""


def build_sql(body):
    """SQL for the single-query modes. Notable runs a two-step flow (aggregate +
    per-player games) handled in search_notable()."""
    mode = body.get("mode")
    if mode == "matchup":
        return sql_matchup(
            _int(body.get("heroA"), 0, 1, 999),
            _int(body.get("heroB"), 0, 1, 999),
            _int(body.get("months"), 6, 1, 120),
            _int(body.get("limit"), 20, 1, 200),
            bool(body.get("require_mid", True)),
            _int(body.get("min_tier"), 0, 0, 90),
        )
    if mode == "raw":
        sql = (body.get("sql") or "").strip()
        if not sql:
            raise ValueError("empty SQL")
        return sql
    raise ValueError(f"unknown mode: {mode}")


def search_notable(body):
    """Two-step Notable search: rank notable players by win rate on the hero (with
    an optional enemy-hero + enemy-lane filter), then fetch each player's individual
    games so the UI can list them inline with download checkboxes."""
    hero = _int(body.get("hero"), 0, 1, 999)
    months = _int(body.get("months"), 3, 1, 60)
    min_games = _int(body.get("min_games"), 5, 1, 1000)
    limit = _int(body.get("limit"), 30, 1, 500)
    vs_hero = _int(body.get("vs_hero"), 0, 0, 999)
    vs_lane = _int(body.get("vs_lane"), 0, 0, 4)

    players_sql = sql_notable(hero, months, min_games, limit, vs_hero, vs_lane)
    players = explorer(players_sql)
    accounts = [p.get("account_id") for p in players if p.get("account_id")]

    games_by_acc = {}
    if accounts:
        try:
            for g in explorer(sql_notable_games(accounts, hero, months, vs_hero, vs_lane)):
                games_by_acc.setdefault(g.get("account_id"), []).append({
                    "match_id": g.get("match_id"),
                    "played": g.get("played"),
                    "won": g.get("won"),
                    "duration": g.get("duration"),
                    "enemy_lane": g.get("enemy_lane"),
                })
        except RuntimeError:
            pass  # degrade gracefully: still show the ranked players, just no inline games

    info = enrich_players(accounts)
    for p in players:
        acc = p.get("account_id")
        ip = info.get(acc) or {}
        p["rank"] = ip.get("rank") or "—"
        p["rank_tier"] = ip.get("rank_tier")
        p["leaderboard_rank"] = ip.get("leaderboard_rank")
        p["_games"] = games_by_acc.get(acc, [])
    return {"rows": players, "sql": players_sql}


# ---------------------------------------------------------------------------
# Download manager (background worker + in-memory job table)
# ---------------------------------------------------------------------------
_jobs = {}
_jobs_lock = threading.Lock()
_dl_queue = queue.Queue()
_cancelled = set()  # match_ids the user asked to cancel; checked by the worker


def _set_job(mid, **kw):
    with _jobs_lock:
        j = _jobs.setdefault(
            mid, {"match_id": mid, "status": "queued", "message": "", "bytes": 0, "total": 0}
        )
        j.update(kw)


def _get_job(mid):
    with _jobs_lock:
        j = _jobs.get(mid)
        return dict(j) if j else None


def _is_cancelled(mid):
    with _jobs_lock:
        return mid in _cancelled


def _finish_cancel(mid):
    with _jobs_lock:
        _cancelled.discard(mid)
    _set_job(mid, status="cancelled", message="cancelled")


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_name(name):
    """Make a user-facing label safe to use as a Windows filename stem."""
    if not name:
        return ""
    return _ILLEGAL.sub("-", str(name)).strip(". ")[:120]


def _parse_match_id(stem):
    """Match id from a replay stem: the whole thing if numeric, else trailing digits
    (descriptive names are written like '..._8861788724'). The Dota client itself reads
    the real match id from inside the .dem, so the filename is only a display label —
    we keep the id in the name purely so this app can dedupe and link the row."""
    if stem.isdigit():
        return int(stem)
    m = re.search(r"(\d{6,})$", stem)
    return int(m.group(1)) if m else None


def _existing_file_for(mid):
    """Path to an already-downloaded .dem for this match id, under ANY filename
    (numeric or descriptive), so re-downloading is skipped regardless of naming."""
    if not os.path.isdir(REPLAY_DIR):
        return None
    for n in os.listdir(REPLAY_DIR):
        if n.lower().endswith(".dem") and _parse_match_id(n[:-4]) == mid:
            return os.path.join(REPLAY_DIR, n)
    return None


def _download_one(mid, name=None):
    if _is_cancelled(mid):  # cancelled while still queued — skip before doing any work
        _finish_cancel(mid)
        return
    # Save as {match_id}.dem — the Dota client lists replays by this numeric name; a
    # descriptive name on disk breaks its Downloaded tab. The readable label is kept in
    # the manifest and shown in the app instead.
    dem = os.path.join(REPLAY_DIR, f"{mid}.dem")
    existing = _existing_file_for(mid)
    if existing:
        _set_name(mid, _safe_name(name))
        _set_job(mid, status="done", message=f"already have it: {os.path.basename(existing)}")
        sync_titles_to_dota("already on disk")
        return

    _set_job(mid, status="resolving", message="fetching replay url")
    r = requests.get(f"{OPENDOTA}/matches/{mid}", params=_params(), timeout=60)
    r.raise_for_status()
    match = r.json()

    url = match.get("replay_url")
    if not url:
        cluster, salt = match.get("cluster"), match.get("replay_salt")
        if cluster and salt:
            url = f"http://replay{cluster}.valve.net/570/{mid}_{salt}.dem.bz2"
    if not url:
        try:
            requests.post(f"{OPENDOTA}/request/{mid}", params=_params(), timeout=30)
        except requests.RequestException:
            pass
        _set_job(mid, status="parsing", message="no replay yet — asked OpenDota to parse it; retry in ~1-2 min")
        return

    os.makedirs(REPLAY_DIR, exist_ok=True)
    _set_job(mid, status="downloading", message="", bytes=0, total=0, url=url)
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    total = int(resp.headers.get("Content-Length", 0) or 0)
    _set_job(mid, total=total)

    decomp = bz2.BZ2Decompressor()
    part = dem + ".part"
    got = 0
    cancelled = False
    try:
        with open(part, "wb") as f:
            for chunk in resp.iter_content(65536):
                if _is_cancelled(mid):  # cancelled mid-stream — stop and clean up
                    cancelled = True
                    break
                if not chunk:
                    continue
                got += len(chunk)
                f.write(decomp.decompress(chunk))
                _set_job(mid, bytes=got)
        if cancelled:
            resp.close()
            _remove_quiet(part)
            _finish_cancel(mid)
            return
        os.replace(part, dem)
    except Exception:
        _remove_quiet(part)
        raise
    _set_name(mid, _safe_name(name))
    _set_job(mid, status="done", message=f"downloaded as {mid}.dem", bytes=got)
    sync_titles_to_dota("after download")  # reflect the readable name inside Dota


def _worker():
    while True:
        item = _dl_queue.get()
        mid, name = item if isinstance(item, tuple) else (item, None)
        try:
            _download_one(mid, name)
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            _set_job(mid, status="error", message=str(e))
        finally:
            _dl_queue.task_done()


for _ in range(DOWNLOAD_WORKERS):
    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Replay folder listing
# ---------------------------------------------------------------------------
_names_lock = threading.Lock()


def _load_names():
    try:
        with open(REPLAY_NAMES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _set_name(mid, label):
    if not label:
        return
    with _names_lock:
        d = _load_names()
        d[str(mid)] = label
        try:
            with open(REPLAY_NAMES, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except OSError:
            pass


def _forget_name(mid):
    with _names_lock:
        d = _load_names()
        if d.pop(str(mid), None) is not None:
            try:
                with open(REPLAY_NAMES, "w", encoding="utf-8") as f:
                    json.dump(d, f)
            except OSError:
                pass


_dota_sync_lock = threading.Lock()


def sync_titles_to_dota(reason=""):
    """Push the app's readable labels into Dota's downloaded_replays_info.dat so the
    custom names show inside the client (Watch -> Downloaded).

    Best-effort and safe: a no-op while Dota is running (it rewrites this file on exit),
    only titles replays whose .dem is actually on disk, and never raises — a sync failure
    must never break a download. Matches Dota hasn't indexed yet get a freshly created
    entry; existing ones are updated in place. replay_titles handles the backup, atomic
    write and CRC recompute."""
    try:
        if replay_titles.dota_running():
            return {"skipped": "dota running"}
        dat = replay_titles.find_dat()
        if not dat:
            return {"skipped": "dat not found"}
        updates = []
        for k, label in _load_names().items():
            try:
                mid = int(k)
            except (TypeError, ValueError):
                continue
            if not label or label == str(mid):
                continue  # raw-mode download — no real custom name
            try:
                size = os.path.getsize(os.path.join(REPLAY_DIR, f"{mid}.dem"))
            except OSError:
                continue  # only title replays that are really on disk
            updates.append({"match_id": mid, "title": label, "size": size})
        if not updates:
            return {"skipped": "nothing to sync"}
        with _dota_sync_lock:
            res = replay_titles.apply(updates, path=dat)
        print(f" Dota names synced ({reason}): set {len(res['set'])}, created {len(res['created'])}")
        return res
    except Exception as e:  # noqa: BLE001 - best effort; must never break the app
        print(f" (Dota name sync skipped: {e})")
        return {"error": str(e)}


def _dota_close_watcher(poll_seconds=15):
    """Background: when Dota 2 goes from running -> closed, flush pending names into its
    replay list. Makes auto-naming work even when you download while Dota is open (we
    can't safely write the file until Dota exits and rewrites it on close)."""
    try:
        prev = replay_titles.dota_running()
    except Exception:  # noqa: BLE001
        prev = False
    while True:
        time.sleep(poll_seconds)
        try:
            now = replay_titles.dota_running()
        except Exception:  # noqa: BLE001
            continue
        if prev and not now:  # Dota just closed -> safe to write
            sync_titles_to_dota("dota closed")
        prev = now


def migrate_descriptive_files():
    """Earlier versions saved replays under descriptive filenames, which the Dota client
    won't list. Rename any such file back to {match_id}.dem and remember its readable
    label in the manifest so the app still shows it. Runs once at startup."""
    if not os.path.isdir(REPLAY_DIR):
        return
    renamed = 0
    for n in list(os.listdir(REPLAY_DIR)):
        if not n.lower().endswith(".dem"):
            continue
        stem = n[:-4]
        if stem.isdigit():
            continue
        mid = _parse_match_id(stem)
        if mid is None:
            continue
        src = os.path.join(REPLAY_DIR, n)
        dst = os.path.join(REPLAY_DIR, f"{mid}.dem")
        try:
            if os.path.exists(dst):
                if os.path.samefile(src, dst):
                    os.remove(src)  # legacy hardlink twin — drop the descriptive name
                else:
                    continue        # a different real file already holds the numeric name
            else:
                os.rename(src, dst)
            _set_name(mid, stem)
            renamed += 1
        except OSError:
            pass
    if renamed:
        print(f" Migrated {renamed} replay(s) back to match-id filenames (labels kept in app)")


def list_replays():
    if not os.path.isdir(REPLAY_DIR):
        return []
    names = _load_names()
    out = []
    for n in os.listdir(REPLAY_DIR):
        if not n.lower().endswith(".dem"):
            continue
        try:
            st = os.stat(os.path.join(REPLAY_DIR, n))
        except OSError:
            continue
        mid = _parse_match_id(n[:-4])
        out.append({
            "name": n,
            "label": (names.get(str(mid)) if mid is not None else None) or n[:-4],
            "match_id": mid,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/config")
def api_config():
    # `dota_sync` is a feature/build marker: the process only reports it once this newer
    # code is loaded, so the UI can show whether app.py still needs a restart.
    return jsonify({"replay_dir": REPLAY_DIR, "has_api_key": bool(API_KEY), "tz": TZ,
                    "dota_sync": True})


@app.route("/api/heroes")
def api_heroes():
    try:
        return jsonify(get_heroes())
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/replays")
def api_replays():
    return jsonify(list_replays())


@app.route("/api/replays/delete", methods=["POST"])
def api_replays_delete():
    """Delete replay file(s) by name. Confined to REPLAY_DIR: basename only (no path
    traversal), must be a .dem. Removes every alias passed (numeric + descriptive)."""
    body = request.get_json(force=True, silent=True) or {}
    names = body.get("names") or ([body["name"]] if body.get("name") else [])
    deleted, errors = [], []
    for raw in names:
        base = os.path.basename(str(raw))
        if base != str(raw) or not base.lower().endswith(".dem"):
            errors.append(f"{raw}: rejected")
            continue
        path = os.path.join(REPLAY_DIR, base)
        try:
            os.remove(path)
            deleted.append(base)
        except FileNotFoundError:
            deleted.append(base)  # already gone — treat as success
        except OSError as e:
            errors.append(f"{base}: {e.strerror or e}")
            continue
        mid = _parse_match_id(base[:-4])
        if mid is not None:
            _forget_name(mid)
    return jsonify({"deleted": deleted, "errors": errors})


@app.route("/api/search", methods=["POST"])
def api_search():
    body = request.get_json(force=True, silent=True) or {}
    sql = ""
    try:
        if body.get("mode") == "notable":
            return jsonify(search_notable(body))
        sql = build_sql(body)
        rows = explorer(sql)
        rows = enrich_rows(body.get("mode"), rows)
        return jsonify({"rows": rows, "sql": sql})
    except ValueError as e:
        return jsonify({"error": str(e), "sql": sql}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e), "sql": sql}), 502


@app.route("/api/launch-dota", methods=["POST"])
def api_launch_dota():
    """Launch Dota 2 via the Steam protocol (appid 570)."""
    try:
        os.startfile("steam://rungameid/570")  # noqa: Windows-only
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sync-dota-titles", methods=["POST"])
def api_sync_dota_titles():
    """Force a name sync into Dota's replay list (handy right after closing Dota)."""
    return jsonify(sync_titles_to_dota("manual"))


@app.route("/api/download", methods=["POST"])
def api_download():
    body = request.get_json(force=True, silent=True) or {}
    # New shape: matches=[{match_id, name}]; fall back to bare match_ids (no readable name).
    items = body.get("matches")
    if items is None:
        items = [{"match_id": m} for m in body.get("match_ids", [])]
    started = []
    for it in items:
        try:
            mid = int((it or {}).get("match_id"))
        except (TypeError, ValueError):
            continue
        name = (it or {}).get("name")
        existing = _existing_file_for(mid)
        cur = _get_job(mid)
        if existing:
            _set_job(mid, status="done", message=f"already have it: {os.path.basename(existing)}", name=name)
        elif cur and cur["status"] in ("queued", "resolving", "downloading"):
            pass  # already in flight
        else:
            _set_job(mid, status="queued", message="", bytes=0, total=0, name=name)
            _dl_queue.put((mid, name))
        started.append(mid)
    return jsonify({"started": started})


@app.route("/api/download/cancel", methods=["POST"])
def api_download_cancel():
    body = request.get_json(force=True, silent=True) or {}
    try:
        mid = int(body.get("match_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad match_id"}), 400
    cur = _get_job(mid)
    if not cur:
        return jsonify({"ok": False, "error": "no such job"}), 404
    if cur["status"] in ("done", "error", "cancelled"):
        return jsonify({"ok": True, "status": cur["status"]})  # nothing to cancel
    with _jobs_lock:
        _cancelled.add(mid)
    if cur["status"] == "queued":
        # worker is busy/sequential — reflect cancellation now; it'll be skipped when popped
        _set_job(mid, status="cancelled", message="cancelled")
    else:
        _set_job(mid, message="cancelling…")  # in flight: the worker loop will finalize
    return jsonify({"ok": True})


@app.route("/api/download/retry", methods=["POST"])
def api_download_retry():
    body = request.get_json(force=True, silent=True) or {}
    try:
        mid = int(body.get("match_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad match_id"}), 400
    cur = _get_job(mid)
    if not cur:
        return jsonify({"ok": False, "error": "no such job"}), 404
    if cur["status"] in ("queued", "resolving", "downloading"):
        return jsonify({"ok": True, "status": cur["status"]})  # already active
    with _jobs_lock:
        _cancelled.discard(mid)
    existing = _existing_file_for(mid)
    if existing:
        _set_job(mid, status="done", message=f"already have it: {os.path.basename(existing)}")
        return jsonify({"ok": True, "status": "done"})
    _set_job(mid, status="queued", message="", bytes=0, total=0)
    _dl_queue.put((mid, cur.get("name")))
    return jsonify({"ok": True, "status": "queued"})


@app.route("/api/downloads")
def api_downloads():
    with _jobs_lock:
        return jsonify(sorted(_jobs.values(), key=lambda j: j["match_id"], reverse=True))


@app.route("/api/downloads/clear", methods=["POST"])
def api_downloads_clear():
    with _jobs_lock:
        for mid in [m for m, j in _jobs.items() if j["status"] in ("done", "error", "parsing")]:
            del _jobs[mid]
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 60)
    print(" Dota 2 Replay Tool")
    print(f" Replay dir : {REPLAY_DIR}")
    print(f" API key    : {'set' if API_KEY else 'not set (free rate limits)'}")
    print(" Open       : http://127.0.0.1:5000")
    print(" Name-sync  : ON (auto-titles replays in Dota on download/startup/Dota-close)")
    print("=" * 60)
    migrate_descriptive_files()  # restore numeric filenames so the Dota client lists them
    sync_titles_to_dota("startup")  # flush any pending readable names into Dota's list
    threading.Thread(target=_dota_close_watcher, daemon=True).start()  # auto-sync on Dota exit
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
