# Running folder guide

## Knowledge base (`knowledge/`)
Before advising on training, plan design, paces, or load management, read the
files in `knowledge/`. They hold Ben's curated training philosophy, distilled
from articles and videos he trusts, and take precedence over generic advice.

When Ben pastes a text dump (YouTube transcript, article) about training:
1. Distill it to principles and concrete rules — never store transcript text
   or filler.
2. If an existing topic file covers the subject, merge and condense into it
   (dedupe across dumps); only create a new kebab-case topic file for a
   genuinely new topic.
3. List every source (title, author/channel, URL, date added) under `Sources:`
   at the top of the topic file.
4. Keep files skimmable: rules and numbers over prose.

## Core principle for all plan advice
Paces and training load are anchored to *current measured fitness* (recent
races in config.json within 90 days, else measured best efforts from Garmin
streams), never to goal times. Do the training needed to reach the next
level, not the training of the level you want to be at.

## Pace conventions
- The Full-Spectrum 10k plan uses **linear percent-of-pace** (Canova-style):
  target pace = base 10k pace * (2 - pct/100), so 90% of 5:24/km = 5:56/km
  and 105% = 5:08/km. Always compute via `scripts/percent.py`.
  (Reference: apps.runningwritings.com/pace-percent)
- Every pace calculation must be persisted: `paces.py` and `percent.py` save
  dated snapshots to `data/paces_history/` automatically — check there for
  what was previously prescribed before recalculating.
- Treadmill/indoor runs are excluded from best-effort pace analysis (their
  pace data is unreliable); they still count toward volume.

## Coach check-in protocol (every ~2 weeks)
When Ben asks for a check-in / coach review:
1. Run `python scripts/sync.py`, then `python scripts/checkin.py` for the
   14-day digest.
2. Ask Ben the 4 subjective questions the digest prints (soreness, early-run
   feel, motivation, how quality sessions felt) if he hasn't said already.
3. Judge against the knowledge base: adherence vs plan, HR vs prescribed
   zones on quality days (tempo should sit <88% max HR / <=LTHR), warning
   signs -> mandatory easy week, volume progression vs the 3-week average.
4. Anchor adjustments are CONSERVATIVE: raise the 10k estimate only after
   ~2 weeks of controlled 95-100% workouts with stable-or-lower HR and no
   warning signs — then by at most 1-2% (a few seconds/km), or preferably
   re-anchor with a parkrun/5k time trial every 4-6 weeks. A new race in
   config.json always re-anchors. Never raise paces from a single good day.
5. If plan changes are needed (illness, missed week), override the affected
   days going forward (plans/overrides.json, or the GUI's per-day edit) —
   rebuild from where he is, don't force the original.

## Layout
- `config.json` stays at the root — the one file Ben edits by hand.
- `scripts/` — all Python tooling. Run everything from the project root as
  `python scripts/<tool>.py` (sibling imports resolve via the script's dir).
- `plans/` — plan JSONs (plan-ingebrigtsen.json = active, plan-fullspectrum.json
  kept as an alternative; switch via config.json plan.active), Ben's per-day
  edits (overrides.json, written by the GUI), and the source plan PDFs.
- `static/` — GUI front-end (index.html plan view, paces.html pace zones).
- `data/` — synced Garmin data, pace snapshots, and the `.garminconnect/`
  token cache (all gitignored).
- `knowledge/` — distilled training philosophy (this is the knowledge base)

## Tooling
- `config.json` — the athlete/race data file: athlete settings (max HR etc.),
  the races list, and the `plan` block: active plan + start_date (a Monday;
  overrides the plan file's own) + optional end_date. Ben edits all of it
  from the GUI, not the file: the program row writes the dates (POST
  /api/plan-config) and the ⚙ button (top right) opens a full settings view
  built as stacked section cards (add future settings as new cards). Its
  Races card manages the races list — add/edit/delete rows with a year
  filter, per-row VDOT and next race / upcoming / anchor chips (GET
  /api/races returns these display fields; PUT /api/races saves the whole
  validated list and strips them). The races list serves double duty: entries with
  times are past results (recent ones anchor paces), and a future-dated
  entry with a blank time IS the next race — auto-detected (earliest date
  >= today, `plan.next_race()`), it sizes the program, phases the weeks and
  injects the race day; the race-day cell's result form fills the time into
  that same entry. All writes keep races one-line formatted so the file
  stays hand-editable as a fallback.
  Plan JSONs in `plans/` are coach-maintained content, not user config.
- `scripts/sync.py` — pull runs + physiology from Garmin into `data/`
- `scripts/analyze.py` — current fitness report; `scripts/paces.py` — Daniels
  training paces
- `scripts/percent.py` — percent-of-pace paces for the Full-Spectrum plan
- `scripts/workout.py` — create + schedule structured workouts in Garmin
  Connect from one line of plan shorthand, e.g.
  `python scripts/workout.py "2km wu, 2x8min @ 95% 5:38/km w/ 2min jog, 1.5km cd" --date today`.
  Work steps get a coded pace-zone target (default +/-5 s/km, `--band`);
  a bare `@ 95%` computes the pace from the live percent-of-pace anchor;
  wu/cd/jog stay target-free. Bare `wu`/`cd` = lap-button step. `--dry-run`
  previews, `--list` / `--delete <id>` manage the library. Workout links
  must be `connect.garmin.com/app/workout/<id>?workoutType=running` — the
  old `/modern/workout/<id>` form 404s.
- `scripts/progress.py` — race VDOTs + saved pace snapshots over time
- `plans/plan-ingebrigtsen.json` + `scripts/plan.py` — the active plan: the
  Ingebrigtsen double-threshold week converted to time (45min easy runs,
  5x6min @ 91-93%, 10x3min / 25x66s @ 95-97%, 20x35s hills, 90min long; gym
  sessions omitted), identical every week — written at elite load (~88 km/wk
  equivalent), Ben scales days down via edits. It stores one `week_template`,
  not fixed weeks: plan.py expands it to however many weeks the config dates
  span (end_date and/or the auto-detected next race, whichever is later;
  default_weeks without either), so the program is never regenerated. Quality
  sessions use bare `wu`/`cd` (lap-button, Ben's preference — only give a
  warm-up a duration when it matters). The next race injects a
  race day into its calendar date and phases the weeks Norwegian-style
  (Bakken/Almgren/Ingebrigtsen + knowledge base): final 5 weeks before race
  week = "specific" (amber highlight — convert one threshold session/week to
  race-pace stepping stones), race week green. The race day cell is green-
  tinted with a 🏁 flag; once the date arrives it shows an "add result"
  button — an inline time/event form (POST /api/race-result) that appends
  to config.json races, so the result re-anchors paces with no hand-editing
  (same-date entries are replaced; click the ✓ to correct a time). plan.py renders weeks with live
  paces, per-day overrides applied, and completion from synced runs.
  `scripts/gui.py` serves it at localhost:5001
  — always-on via `docker compose up -d --build`, hot-reloads on any edit;
  paginated 4-week calendar. Every day is editable in place (plan shorthand;
  "rest" = off day; saved to plans/overrides.json keyed by date, with a
  "↺ original" button to undo) and every upcoming day has a "create workout"
  button that pushes the session to Garmin via workout.py, scheduled on
  that date. Doubles days ("AM: ...; PM: ...") are handled per session: the
  editor shows one field per session (blank/"rest" drops that half) and
  create/delete buttons come in AM/PM pairs (POST /api/workout with
  session "am"/"pm"; whole-day create on a doubles day is rejected, the
  Garmin name gets an AM/PM prefix, bookkeeping keys are "date:am"/":pm")
  — created workouts are remembered in data/created_workouts.json
  and get a "delete" button (DELETE /api/workout/<id>) so one-shot sessions
  don't pile up in the Garmin library. The Workouts tab lists the whole Garmin
  workout library (GET /api/garmin-workouts: name, steps, est. time, created,
  scheduled date) with a delete button per row — view-and-delete only, no
  editing; paces, health and mileage in the Stats tab
  (its refresh button recalculates paces and saves the daily snapshot; the
  mileage view plots weekly pace and flags volume spikes >1.4x the 3-week
  avg and weeks where HR is >10% less efficient than the recent baseline).
  The Activities tab lists every synced run (sortable, filterable by
  outdoor/indoor, period, effort, name) with an effort score = Banister
  TRIMP (duration x HR-reserve), bucketed easy->max by quantiles of Ben's
  own run history.
- Pace re-anchoring cadence (per Full-Spectrum article): every 2-4 weeks, or
  after any race; judge from how 90-105% workouts feel. The plan renders from
  the live anchor, so adding a race to config.json updates every workout pace.
