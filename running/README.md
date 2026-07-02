# Running Analysis

Pulls running data from Garmin Connect (via the unofficial `garminconnect`
library — the official Garmin API is business-partners-only) and turns it into
a current-fitness assessment and training paces for structured plans.

Core principle: **paces are anchored to current measured fitness, not goal
times**. You do the training needed to get to the next level — not the training
of the level you want to be at.

## Setup

```
pip install -r requirements.txt
copy .env.example .env     # fill in your Garmin email/password
```

Credentials are only needed once — the first login caches OAuth tokens in
`data/.garminconnect/` (valid ~1 year). If your account has MFA, you'll be
prompted for the code on first login.

This project has no venv — the CLI tools run on system Python. If your shell
prompt shows another project's `(.venv)` active, `deactivate` first, or the
imports (pandas etc.) will fail.

## Layout

`config.json` (the file you edit) sits at the root; all Python tools live in
`scripts/`, plan JSONs and source PDFs in `plans/`, the GUI front-end in
`static/`, synced Garmin data in `data/`, and distilled training philosophy
in `knowledge/`.

## Web GUI

One-time: `docker compose up -d --build`. The plan GUI then lives at
http://127.0.0.1:5001 permanently — the container restarts with Docker
Desktop, so there is nothing to launch. Edits hot-reload: Flask restarts on
.py changes and the pages refresh themselves whenever code, plans, or
config.json change. Re-run the build command only when requirements.txt
changes. (Without Docker, `python scripts/gui.py` still works.)

## Usage

Day-to-day everything lives in the GUI: Sync Garmin, the plan calendar, pace
zones, health stats, best efforts, and mileage. The CLI below is for coach
workflows (check-ins, progression review) and debugging:

```
python scripts/sync.py      # download runs (last 365 days) + physiology snapshot
python scripts/analyze.py   # current fitness report
python scripts/paces.py     # Daniels training paces from measured fitness
python scripts/paces.py --race 10k 52:30   # anchor on a real recent race instead
python scripts/checkin.py   # 14-day digest for the fortnightly coach review
python scripts/progress.py  # VDOT + prescribed paces over time
```

Re-running `sync.py` is cheap — already-downloaded activities are skipped.

## config.json

The one file you edit. Three blocks: `athlete` (max/resting/lactate-threshold
HR overrides — leave null to derive from Garmin data), `races` (add each new
race as `{event, date, distance_m, time}` — pace and VDOT are computed, never
entered; a race within the last 90 days automatically becomes the pace
anchor), and `plan` (which plan the tools execute and its start date, a
Monday). Plan files in `plans/` are generated/maintained content — you never
need to touch them.

## What each piece does

- `sync.py` — downloads every run (summary, GPS/HR streams, splits, HR-in-zones)
  into `data/activities/`, builds `data/activities.csv`, and snapshots
  physiology (VO2max, lactate threshold, race predictions, training status,
  PRs, resting HR) into `data/physiology.json`.
- `analyze.py` — weekly volume, best rolling 1k/1mi/3k/5k/10k efforts computed
  from the raw streams (last 8 weeks), Garmin physiology, and a current VDOT
  verdict (measured vs. Garmin's optimistic predictor).
- `paces.py` — Daniels E/M/T/I/R training paces, equivalent race times, and HR
  zones (from lactate threshold HR and observed max HR).
- `vdot.py` — Jack Daniels' VDOT equations (shared math).

## Training plan workflow

1. Drop the plan PDF into `plans/`.
2. Run `sync.py` so the data is fresh.
3. Ask Claude to read the PDF and translate every workout into concrete paces
   and HR targets using the current `analyze.py` / `paces.py` output.
4. Re-sync and re-check paces every few weeks — as fitness improves, the
   measured VDOT rises and paces update automatically.
