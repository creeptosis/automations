"""Create (and schedule) a structured workout in Garmin Connect from one line.

Speaks the same shorthand the plan uses. Comma-separated steps:

    python scripts/workout.py "2km wu @ 7:30, 2x8min @ 95% 5:38/km w/ 2min jog, 1.5km cd @ 7:46" --date today
    python scripts/workout.py "wu, 5x400m @ 105% w/ 200m jog, cd" --date 2026-07-10
    python scripts/workout.py "3km wu, 25x66s @ 4:45 w/ 30s jog, 2km cd" --dry-run

Step grammar (case-insensitive):
    [Nx] <qty> [wu|cd] [@ [pct%] [m:ss[/km]]] [w/ <qty> jog]
    - qty: 2km, 400m, 8min, 66s. Bare "wu" / "cd" = press-lap-to-advance.
    - Work steps get a coded pace-zone target (pace +/- --band s/km).
      If only a percent is given, the pace is computed from the live
      percent-of-pace anchor (same as scripts/percent.py) and snapshotted.
    - wu / cd / jog steps stay target-free (beep-free); any pace mentioned
      is kept as the step note.
    --date today|tomorrow|YYYY-MM-DD schedules it on the Garmin calendar.
    --list shows the library, --delete <id> removes a workout.
"""

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from garmin_client import get_client

# Garmin workout-service ids (verified against workouts fetched from Ben's account)
SPORT_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
}
END_LAP = {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True}
END_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
END_DIST = {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True}
END_ITER = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False}
TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
TARGET_PACE = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}

QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(km|min(?:s)?|m|s(?:ec)?(?:s)?)\b", re.I)
PACE_RE = re.compile(r"(\d+):(\d{2})\s*(?:/km)?")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
REPS_RE = re.compile(r"^(\d+)\s*[x×]\s*(.+)$", re.I)


def fmt_pace(s_per_km: float) -> str:
    return f"{int(s_per_km // 60)}:{int(round(s_per_km % 60)):02d}/km"


def parse_qty(text: str):
    """First quantity in text -> ('distance', meters) / ('time', seconds) / None."""
    m = QTY_RE.search(text)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2).lower()
    if unit == "km":
        return ("distance", val * 1000)
    if unit == "m":
        return ("distance", val)
    if unit.startswith("min"):
        return ("time", val * 60)
    return ("time", val)


def qty_str(kind: str, value: float) -> str:
    if kind == "distance":
        return f"{value / 1000:g}km" if value >= 1000 else f"{value:g}m"
    return f"{value / 60:g}min" if value % 60 == 0 and value >= 60 else f"{value:g}s"


class Spec:
    """One parsed step: role, end condition, optional pace/pct, optional recovery."""

    def __init__(self, role, end, pace=None, pct=None, reps=None, recovery=None,
                 notarget=False):
        self.role, self.end, self.pace, self.pct = role, end, pace, pct
        self.reps, self.recovery = reps, recovery
        self.notarget = notarget  # work step that should stay beep-free (easy/long)


def parse_target(text: str):
    """Return (pace_s_per_km or None, pct or None) from the part after '@'."""
    pct = PCT_RE.search(text)
    pace = PACE_RE.search(text)
    pace_s = int(pace.group(1)) * 60 + int(pace.group(2)) if pace else None
    return pace_s, float(pct.group(1)) if pct else None


def parse_step(text: str) -> Spec:
    text = text.strip()
    reps = None
    m = REPS_RE.match(text)
    if m:
        reps, text = int(m.group(1)), m.group(2)

    recovery = None
    parts = re.split(r"\bw(?:/|ith)\s*", text, maxsplit=1, flags=re.I)
    if len(parts) == 2:
        text, rec_text = parts
        rec_end = parse_qty(rec_text) or ("lap", 0)
        recovery = Spec("recovery", rec_end)

    notarget = False
    if re.search(r"\b(wu|warm\s*-?up)\b", text, re.I):
        role = "warmup"
    elif re.search(r"\b(cd|cool\s*-?down|wd)\b", text, re.I):
        role = "cooldown"
    elif re.search(r"\b(jog|rest|recovery|walk)\b", text, re.I) and not reps:
        role = "recovery"
    else:
        role = "interval"
        # easy/long/steady mileage: keep the pace as a note, not a beeping target
        notarget = bool(re.search(r"\b(easy|steady|long)\b", text, re.I))

    target_text = text.split("@", 1)[1] if "@" in text else ""
    pace, pct = parse_target(target_text)
    end = parse_qty(text.split("@", 1)[0]) or ("lap", 0)
    if reps and recovery is None:
        recovery = Spec("recovery", ("lap", 0))  # repeat needs a rest step
    return Spec(role, end, pace, pct, reps, recovery, notarget)


def parse_spec(text: str) -> list:
    """Full spec -> Spec list. Steps separate on ',' or ' + ' (plan style)."""
    return [parse_step(p) for p in re.split(r",|\s\+\s", text) if p.strip()]


def resolve_percent_paces(specs):
    """Fill pace from pct via the live anchor when only a percent was given."""
    needed = [s for s in specs if s.pace is None and s.pct is not None
              and s.role == "interval" and not s.notarget]
    if not needed:
        return None
    import percent

    base, source = percent.derive_base(argparse.Namespace(base=None, tenk=None))
    for s in needed:
        s.pace = percent.pace_at_percent(base, s.pct)
    return f"paces from {source}"


def end_condition(end):
    kind, value = end
    cond = {"lap": END_LAP, "time": END_TIME, "distance": END_DIST}[kind]
    return dict(cond), float(value)


def executable_step(order, spec, band, child_id=None):
    cond, value = end_condition(spec.end)
    step = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(STEP_TYPES[spec.role]),
        "childStepId": child_id,
        "endCondition": cond,
        "endConditionValue": value,
        "targetType": dict(TARGET_NONE),
        "targetValueOne": None,
        "targetValueTwo": None,
    }
    note = []
    if spec.pct is not None:
        note.append(f"{spec.pct:g}%")
    if spec.pace is not None:
        note.append(fmt_pace(spec.pace))
    if spec.role == "interval" and spec.pace is not None and not spec.notarget:
        slow, fast = spec.pace + band, spec.pace - band
        step["targetType"] = dict(TARGET_PACE)
        step["targetValueOne"] = 1000.0 / slow   # m/s, slow edge
        step["targetValueTwo"] = 1000.0 / fast   # m/s, fast edge
        step["description"] = " ".join(note)
    elif note:
        step["description"] = "@ " + " ".join(note)  # info only, no beeping target
    return step


def build_steps(specs, band):
    steps, order, child = [], 1, 0
    for spec in specs:
        if spec.reps:
            child += 1
            work = executable_step(order + 1, spec, band, child)
            rec = executable_step(order + 2, spec.recovery, band, child)
            steps.append({
                "type": "RepeatGroupDTO",
                "stepOrder": order,
                "stepType": dict(STEP_TYPES["repeat"]),
                "childStepId": child,
                "numberOfIterations": spec.reps,
                "smartRepeat": False,
                "endCondition": dict(END_ITER),
                "endConditionValue": float(spec.reps),
                "workoutSteps": [work, rec],
            })
            order += 3
        else:
            steps.append(executable_step(order, spec, band))
            order += 1
    return steps


def estimate_seconds(specs) -> int:
    """Rough duration for the calendar tile (7:30/km assumed where pace unknown)."""
    total = 0.0
    for spec in specs:
        for s in ([spec, spec.recovery] if spec.reps else [spec]):
            kind, value = s.end
            sec = value if kind == "time" else (value / 1000) * (s.pace or 450) if kind == "distance" else 300
            total += sec * (spec.reps or 1) if spec.reps else sec
    return int(total)


def auto_name(specs) -> str:
    for spec in specs:
        if spec.reps:
            name = f"{spec.reps}x{qty_str(*spec.end)}"
            if spec.pace:
                name += f" @ {fmt_pace(spec.pace)}"
            return name
    work = [s for s in specs if s.role == "interval"] or specs
    name = qty_str(*work[0].end) if work[0].end[0] != "lap" else "Run"
    return name + (f" @ {fmt_pace(work[0].pace)}" if work[0].pace else "")


def describe(steps, indent="  "):
    lines = []
    for s in steps:
        if s["type"] == "RepeatGroupDTO":
            lines.append(f"{indent}{s['numberOfIterations']}x:")
            lines += describe(s["workoutSteps"], indent + "  ")
            continue
        kind = s["stepType"]["stepTypeKey"]
        cond = s["endCondition"]["conditionTypeKey"]
        end = "lap button" if cond == "lap.button" else qty_str(
            "time" if cond == "time" else "distance", s["endConditionValue"])
        tgt = ""
        if s["targetType"]["workoutTargetTypeKey"] == "pace.zone":
            tgt = f"  target {fmt_pace(1000 / s['targetValueTwo'])} - {fmt_pace(1000 / s['targetValueOne'])}"
        elif s.get("description"):
            tgt = f"  ({s['description']})"
        lines.append(f"{indent}{kind:<9} {end}{tgt}")
    return lines


def resolve_date(text):
    if not text:
        return None
    text = text.lower()
    if text == "today":
        return date.today().isoformat()
    if text == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()
    return date.fromisoformat(text).isoformat()


def create(spec_text, name=None, band=5.0, date_str=None, client=None) -> dict:
    """Parse a spec, upload it to Garmin, optionally schedule it. Used by the
    CLI below and by the plan GUI's per-day button."""
    specs = parse_spec(spec_text)
    anchor_note = resolve_percent_paces(specs)
    steps = build_steps(specs, band)
    name = name or auto_name(specs)
    payload = {
        "workoutName": name,
        "description": spec_text,
        "sportType": dict(SPORT_RUNNING),
        "estimatedDurationInSecs": estimate_seconds(specs),
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": dict(SPORT_RUNNING), "workoutSteps": steps}
        ],
    }
    client = client or get_client()
    result = client.upload_workout(payload)
    if hasattr(result, "json"):
        result = result.json()
    wid = result["workoutId"]
    when = resolve_date(date_str)
    if when:
        client.schedule_workout(wid, when)
    return {
        "id": wid,
        "name": name,
        "date": when,
        # /app/... + workoutType: the /modern/... form 404s in current Connect
        "url": f"https://connect.garmin.com/app/workout/{wid}?workoutType=running",
        "steps": describe(steps),
        "anchor_note": anchor_note,
    }


def main():
    p = argparse.ArgumentParser(description="Create a Garmin Connect workout from shorthand")
    p.add_argument("spec", nargs="?", help='e.g. "2km wu, 2x8min @ 5:38 w/ 2min jog, 1.5km cd"')
    p.add_argument("--name", help="workout name (default: auto from the main set)")
    p.add_argument("--date", help="schedule on: today | tomorrow | YYYY-MM-DD")
    p.add_argument("--band", type=float, default=5.0, help="pace target half-width, s/km (default 5)")
    p.add_argument("--dry-run", action="store_true", help="print the payload, don't upload")
    p.add_argument("--list", action="store_true", help="list workouts in the library")
    p.add_argument("--delete", metavar="ID", help="delete a workout by id")
    args = p.parse_args()

    if args.list or args.delete:
        client = get_client()
        if args.delete:
            client.delete_workout(args.delete)
            print(f"Deleted workout {args.delete}")
        else:
            for w in client.get_workouts(0, 50):
                print(f"  {w['workoutId']}  {w.get('workoutName', '')}")
        return

    if not args.spec:
        p.error("give a workout spec (or --list / --delete)")

    if args.dry_run:
        specs = parse_spec(args.spec)
        anchor_note = resolve_percent_paces(specs)
        steps = build_steps(specs, args.band)
        print(f"Workout: {args.name or auto_name(specs)}")
        print("\n".join(describe(steps)))
        if anchor_note:
            print(f"  ({anchor_note})")
        print(json.dumps(steps, indent=2))
        return

    r = create(args.spec, name=args.name, band=args.band, date_str=args.date)
    print(f"Workout: {r['name']}")
    print("\n".join(r["steps"]))
    if r["anchor_note"]:
        print(f"  ({r['anchor_note']})")
    print(f"\nCreated: {r['url']}")
    if r["date"]:
        print(f"Scheduled on {r['date']} - it will show on the watch after it syncs.")


if __name__ == "__main__":
    main()
