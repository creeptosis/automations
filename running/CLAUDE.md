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
5. If plan changes are needed (illness, missed week), edit plans/plan.json
   weeks going forward — rebuild from where he is, don't force the original.

## Layout
- `config.json` stays at the root — the one file Ben edits by hand.
- `scripts/` — all Python tooling. Run everything from the project root as
  `python scripts/<tool>.py` (sibling imports resolve via the script's dir).
- `plans/` — the active plan JSONs (plan.json, plan-fullspectrum.json) plus
  the source training-plan PDFs.
- `static/` — GUI front-end (index.html plan view, paces.html pace zones).
- `data/` — synced Garmin data, pace snapshots, and the `.garminconnect/`
  token cache (all gitignored).
- `knowledge/` — distilled training philosophy (this is the knowledge base)

## Tooling
- `config.json` — THE single hand-edited file: athlete settings (max HR etc.),
  race history (VDOT computed), and the `plan` block (which plan is active +
  its start_date, a Monday; overrides the plan file's own start_date).
  Plan JSONs in `plans/` are coach-maintained content, not user config.
- `scripts/sync.py` — pull runs + physiology from Garmin into `data/`
- `scripts/analyze.py` — current fitness report; `scripts/paces.py` — Daniels
  training paces
- `scripts/percent.py` — percent-of-pace paces for the Full-Spectrum plan
- `scripts/progress.py` — race VDOTs + saved pace snapshots over time
- `plans/plan.json` + `scripts/plan.py` — the active 16-week plan (Brant weekly
  template, Full-Spectrum progressions); plan.py renders weeks with live paces
  and completion from synced runs. `scripts/gui.py` serves it at localhost:5001
  — always-on via `docker compose up -d --build`, hot-reloads on any edit;
  paginated 4-week calendar; paces, health and mileage in the Stats tab
  (its refresh button recalculates paces and saves the daily snapshot; the
  mileage view plots weekly pace and flags volume spikes >1.4x the 3-week
  avg and weeks where HR is >10% less efficient than the recent baseline).
- Pace re-anchoring cadence (per Full-Spectrum article): every 2-4 weeks, or
  after any race; judge from how 90-105% workouts feel. The plan renders from
  the live anchor, so adding a race to config.json updates every workout pace.
