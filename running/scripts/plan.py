"""Render the training plan with concrete paces and completion status.

Reads plans/plan.json, annotates every "NN%" in workouts with the actual pace from
the current fitness anchor, and marks days complete by matching synced Garmin
runs (a day counts as done if actual km >= 70% of planned km).

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
    "brant": "plans/plan.json",
    "davis": "plans/plan-fullspectrum.json",
}
DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def plan_config() -> dict:
    """The 'plan' block of config.json - the single file Ben edits."""
    path = BASE_DIR / "config.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("plan") or {}


def active_plan() -> str:
    return plan_config().get("active", "brant")


def load_plan(name: str | None = None) -> dict:
    name = name or active_plan()
    p = json.loads((BASE_DIR / PLAN_FILES[name]).read_text(encoding="utf-8"))
    # config.json owns the start date of the plan being executed; reference
    # plans keep their own
    start = plan_config().get("start_date")
    if start and name == active_plan():
        p["start_date"] = start
    return p


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
    print(f"WEEK {week['week']}/16  ({week['phase']})  target ~{week['volume_km']}km")
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

    plan = load_plan(args.plan)
    base, source = current_anchor()

    if args.all:
        print_all(plan, base)
        return
    week_no = args.week or current_week_no(plan)
    print_week(plan, week_no, base, source)


if __name__ == "__main__":
    main()
