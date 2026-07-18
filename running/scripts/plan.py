"""Render the training plan with concrete paces and completion status.

Reads the active plan JSON (plans/plan-fullspectrum.json), applies Ben's
per-day edits from plans/overrides.json, annotates every "NN%" in workouts with
the actual pace from the current fitness anchor, and marks days complete by
matching synced Garmin runs (a day counts as done if actual km >= 70% of
planned km).

Usage:
    python scripts/plan.py             # current week
    python scripts/plan.py --week 3    # a specific week
    python scripts/plan.py --all       # one-line-per-week overview of quality sessions
"""

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import percent

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
PLAN_FILES = {
    "fullspectrum": "plans/plan-fullspectrum.json",
    "ingebrigtsen": "plans/plan-ingebrigtsen.json",
}
OVERRIDES_FILE = BASE_DIR / "plans" / "overrides.json"
DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def plan_config() -> dict:
    """The 'plan' block of config.json - the single file Ben edits."""
    path = BASE_DIR / "config.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("plan") or {}


def active_plan() -> str:
    return plan_config().get("active", "fullspectrum")


# race-specific block per the knowledge base + Bakken/Almgren/Ingebrigtsen
# practice: the final weeks before the race convert threshold work to race
# pace; race week itself is its own phase. When the plan carries
# specific_phase overlays, the "specific" label follows the weeks the
# variant actually rewrites (5k/10k build = 5 weeks, the Almgren HM
# conversion = 3); this is the fallback for plans without overlays.
SPECIFIC_WEEKS = 5


def expand_template(p: dict, cfg: dict) -> list:
    """Generate the weeks of a repeating-week plan. Length comes from the
    config end_date and/or the auto-detected next race (whichever is later),
    falling back to the plan's default_weeks. The race day replaces its
    template day and the weeks before it get specific/race-week phases,
    with their days rewritten from the plan's specific_phase overlays
    (keyed by weeks-before-race-week; 5k/10k variant from race distance)."""
    start = date.fromisoformat(p["start_date"])
    race = next_race() or {}
    race_day = date.fromisoformat(race["date"]) if race.get("date") else None
    ends = [date.fromisoformat(cfg["end_date"])] if cfg.get("end_date") else []
    if race_day:
        ends.append(race_day)
    n = (max(1, (max(ends) - start).days // 7 + 1) if ends
         else int(p.get("default_weeks", 16)))
    race_week = ((race_day - start).days // 7 + 1
                 if race_day and race_day >= start else None)

    tmpl = p["week_template"]
    # base->specific transition (knowledge/base-to-specific-transition.md):
    # the specific_phase block swaps individual days in the final weeks so
    # one session per week turns toward race pace while the rest of the
    # identical base week keeps running
    overlays = {}
    if race_week and p.get("specific_phase"):
        dist = float(race.get("distance_m") or 10000)
        variant = "5k" if dist <= 6000 else "10k" if dist <= 15000 else "half"
        overlays = p["specific_phase"].get(variant) or {}
    spec_weeks = ({int(k) for k in overlays if k != "0"}
                  or set(range(1, SPECIFIC_WEEKS + 1)))
    weeks = []
    for i in range(1, n + 1):
        phase = "base"
        days = dict(tmpl["days"])
        volume = tmpl.get("volume_km", 0)
        if race_week:
            if i == race_week:
                phase = "race week"
            elif (race_week - i) in spec_weeks:
                phase = "specific"
            ov = overlays.get(str(race_week - i))
            if ov:
                days.update({d: ov[d] for d in DAY_ORDER if d in ov})
                volume = ov.get("volume_km", volume)
        weeks.append({"week": i, "phase": phase,
                      "volume_km": volume, "days": days})
    if race_week and race_week <= n:
        km = float(race.get("distance_m") or 10000) / 1000
        weeks[race_week - 1]["days"][DAY_ORDER[race_day.weekday()]] = {
            "type": "race", "km": km,
            "workout": race.get("event") or f"{km:g}km RACE",
        }
    return weeks


def load_plan(name: str | None = None) -> dict:
    name = name or active_plan()
    p = json.loads((BASE_DIR / PLAN_FILES[name]).read_text(encoding="utf-8"))
    # config.json owns the dates of the plan being executed; reference
    # plans keep their own
    cfg = plan_config() if name == active_plan() else {}
    if cfg.get("start_date"):
        p["start_date"] = cfg["start_date"]
    if p.get("week_template"):
        p["weeks"] = expand_template(p, cfg)
    return p


def next_race() -> dict | None:
    """The next race, auto-detected from config.json's races list: the
    earliest entry dated today or later (add the upcoming race in the GUI's
    settings modal; its result gets filled in from the race-day cell)."""
    today = date.today().isoformat()
    upcoming = [r for r in json.loads((BASE_DIR / "config.json")
                                      .read_text(encoding="utf-8")).get("races", [])
                if r.get("date", "") >= today]
    return min(upcoming, key=lambda r: r["date"]) if upcoming else None


def load_overrides() -> dict:
    """ISO date -> replacement day dict (Ben's per-day edits from the GUI)."""
    if OVERRIDES_FILE.exists():
        return json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    return {}


def save_overrides(overrides: dict) -> None:
    OVERRIDES_FILE.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")


def _km_estimate(low: str) -> float:
    """Total km implied by an edit's text: 'NxMkm' counts N*M, ranges like
    '11-13km' count their top end, plain 'Nkm' counts once - all summed, so
    '2km wu, 3x2km @ 100%, 2km cd' -> 10."""
    reps = r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*km"
    rng = r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*km"
    total = sum(int(n) * float(k) for n, k in re.findall(reps, low))
    low = re.sub(reps, "", low)
    total += sum(max(float(a), float(b)) for a, b in re.findall(rng, low))
    low = re.sub(rng, "", low)
    total += sum(float(k) for k in re.findall(r"(\d+(?:\.\d+)?)\s*km", low))
    return total


def day_from_text(text: str) -> dict:
    """Turn a free-text day edit into a plan-day dict. 'rest'/'off' (or blank)
    means an off day; anything else becomes the day's workout string, with the
    type guessed from keywords and km summed from the 'NNkm' quantities."""
    t = " ".join(text.split())
    low = t.lower()
    if low in ("", "rest", "off", "-"):
        return {"type": "off"}
    if re.search(r"\b\d+\s*(?:x|×|sets?\b)", low) or "interval" in low:
        typ = "intervals"
    elif "long" in low:
        typ = "long"
    elif re.search(r"\b(tempo|threshold|progression)\b", low):
        typ = "tempo"
    elif "race" in low:
        typ = "race"
    else:
        typ = "easy"
    day = {"type": typ, "workout": t}
    km = _km_estimate(low)
    if km:
        day["km"] = round(km, 1)
    return day


_AMPM_RE = re.compile(r"^\s*AM:\s*(.*?)\s*;\s*PM:\s*(.*)$", re.S | re.I)


def split_sessions(day: dict) -> dict | None:
    """{'am': text, 'pm': text} for a doubles day ('AM: ...; PM: ...'),
    else None. Texts are raw shorthand, each a valid workout spec alone."""
    m = _AMPM_RE.match(day.get("workout") or "")
    return {"am": m.group(1), "pm": m.group(2)} if m else None


def apply_overrides(plan: dict) -> dict:
    """Swap edited days in (keyed by ISO date in plans/overrides.json). Each
    replaced day is tagged _edited so the GUI can offer a restore button."""
    overrides = load_overrides()
    if not overrides:
        return plan
    for w in plan["weeks"]:
        dates = week_dates(plan, w["week"])
        for d in DAY_ORDER:
            o = overrides.get(dates[d])
            if o:
                day = dict(o)
                day["_edited"] = True
                w["days"][d] = day
    return plan


def current_anchor() -> tuple[float, str]:
    ns = argparse.Namespace(base=None, tenk=None)
    return percent.derive_base(ns)


# effort words -> % of 10k pace (from the Full-Spectrum PDF's own table);
# combos listed first so the regex prefers the longest match
EFFORT_ZONES = [
    ("very easy to easy", 45, 65),
    ("easy to moderate", 55, 80),
    ("moderate to strong", 70, 90),
    ("very easy", 45, 55),
    ("easy", 55, 65),
    ("moderate", 70, 80),
    ("strong", 85, 90),
]
_EFFORT_RE = re.compile(
    r"\b(" + "|".join(z[0] for z in EFFORT_ZONES) + r")\b(?!\s*(?:to\b|@))"
)
_EFFORT_MAP = {z[0]: (z[1], z[2]) for z in EFFORT_ZONES}


def annotate_efforts(text: str) -> str:
    """Give bare effort words explicit percentages so annotate() can attach
    paces: '11-13km easy' -> '11-13km easy @ 55-65%'. Words already followed
    by '@' or 'to' are left alone."""
    def repl(m):
        lo, hi = _EFFORT_MAP[m.group(1)]
        return f"{m.group(1)} @ {lo}-{hi}%"

    return _EFFORT_RE.sub(repl, text)


def annotate(text: str, base: float) -> str:
    """'20min @ 96%' -> '20min @ 96% [5:31/km]'. Ranges use both ends."""
    def repl(m):
        if m.group(2):  # range like 95-96%
            lo = percent.fmt(percent.pace_at_percent(base, float(m.group(2))))
            hi = percent.fmt(percent.pace_at_percent(base, float(m.group(1))))
            return f"{m.group(0)} [{lo}-{hi}]"
        return f"{m.group(0)} [{percent.fmt(percent.pace_at_percent(base, float(m.group(1))))}]"

    return re.sub(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?\s*%", repl, text)


def describe(day: dict, base: float) -> str:
    if day["type"] == "off":
        return "off"
    if day.get("workout"):
        return annotate(annotate_efforts(day["workout"]), base)
    if day["type"] == "easy":
        return annotate(f"{day['km']}km easy @ 55-65%", base)
    if day["type"] == "long":
        return annotate(f"{day['km']}km long run @ 60-70%", base)
    return f"{day.get('km', '?')}km"


def actual_km_by_date() -> dict:
    """date iso -> total km run that day (from the sync index)."""
    index = BASE_DIR / "data" / "activities.csv"
    totals = {}
    if not index.exists():
        return totals
    import pandas as pd

    df = pd.read_csv(index)
    for _, row in df.iterrows():
        day = str(row["start_time"])[:10]
        totals[day] = totals.get(day, 0.0) + float(row["distance_km"] or 0)
    return totals


def week_dates(plan: dict, week_no: int) -> dict:
    start = date.fromisoformat(plan["start_date"]) + timedelta(weeks=week_no - 1)
    return {d: (start + timedelta(days=i)).isoformat() for i, d in enumerate(DAY_ORDER)}


def current_week_no(plan: dict) -> int:
    delta = (date.today() - date.fromisoformat(plan["start_date"])).days
    return max(1, min(len(plan["weeks"]), delta // 7 + 1))


def status_mark(day: dict, day_date: str, actuals: dict) -> str:
    today = date.today().isoformat()
    if day_date > today:
        return " "
    done = actuals.get(day_date, 0.0)
    if day["type"] == "off":
        return "-"
    planned = float(day.get("km", 0))
    if done >= 0.7 * planned and planned > 0:
        return "X"
    if done > 0:
        return "~"  # partial
    return "." if day_date < today else " "


def print_week(plan: dict, week_no: int, base: float, source: str) -> None:
    week = plan["weeks"][week_no - 1]
    dates = week_dates(plan, week_no)
    actuals = actual_km_by_date()
    today = date.today().isoformat()

    print("=" * 70)
    print(f"WEEK {week['week']}/{len(plan['weeks'])}  ({week['phase']})  "
          f"target ~{week['volume_km']}km")
    print(f"paces from: {source}")
    print("legend: X done  ~ partial  . missed  - rest")
    print("=" * 70)
    for d in DAY_ORDER:
        day = week["days"][d]
        mark = status_mark(day, dates[d], actuals)
        arrow = "  <-- TODAY" if dates[d] == today else ""
        print(f" [{mark}] {d.capitalize():<4} {dates[d][5:]}  {describe(day, base)}{arrow}")


def print_all(plan: dict, base: float) -> None:
    print(f"{plan['name']}  (start {plan['start_date']})")
    for w in plan["weeks"]:
        tue = w["days"]["tue"].get("workout", "easy")
        fri = w["days"]["fri"].get("workout", "easy")
        key = lambda s: re.sub(r"\d+(?:\.\d+)?km wu[^,]*, ", "", s).split(",")[0]
        print(f"  wk {w['week']:>2} ({w['phase']:<13} ~{w['volume_km']}km)  "
              f"Tue: {key(tue):<42} Fri: {key(fri)}")


def main():
    parser = argparse.ArgumentParser(description="Show the training plan with live paces")
    parser.add_argument("--week", type=int, help="week number (default: current)")
    parser.add_argument("--all", action="store_true", help="whole-plan overview")
    parser.add_argument("--plan", choices=list(PLAN_FILES), default=None,
                        help="which plan (default: the active plan from config.json)")
    args = parser.parse_args()

    plan = apply_overrides(load_plan(args.plan))
    base, source = current_anchor()

    if args.all:
        print_all(plan, base)
        return
    week_no = args.week or current_week_no(plan)
    print_week(plan, week_no, base, source)


if __name__ == "__main__":
    main()
