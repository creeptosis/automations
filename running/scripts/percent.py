"""Percent-of-pace calculator (RunningWritings / Canova convention).

John Davis's percentages apply LINEARLY to pace, symmetric around 100%:

    target pace = base pace * (2 - pct / 100)

Each 10% step is the same pace increment (90% of 5:00/mi = 5:30, 80% = 6:00).
So 90% of 5:24/km = 5:56/km, 95% = 5:40/km, 105% = 5:08/km.
See knowledge/percentage-based-10k-training.md and
https://apps.runningwritings.com/pace-percent/

Usage:
    python scripts/percent.py                     # current 10k fitness, standard zones
    python scripts/percent.py --tenk 53:42       # anchor on a specific 10k time
    python scripts/percent.py --base 5:24        # anchor on a base pace directly
    python scripts/percent.py --tenk 53:42 90 95 100 105   # custom percentages
Every run saves a snapshot to data/paces_history/.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import vdot

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
HISTORY_DIR = BASE_DIR / "data" / "paces_history"

STANDARD_ZONES = [
    (45, "very easy (recovery/doubles)"),
    (55, "easy (low end)"),
    (65, "easy (high end)"),
    (70, "moderate (low end)"),
    (80, "moderate high / long fast low"),
    (85, "long fast / strong"),
    (90, "10k-supportive endurance"),
    (93, "sub-threshold"),
    (95, "10k-specific endurance"),
    (97, "classical lactate threshold"),
    (100, "10k race pace"),
    (105, "10k-specific speed (~5k pace)"),
    (110, "10k-supportive speed"),
    (115, "3k/1500m pace"),
]


def pace_at_percent(base_s_per_km: float, pct: float) -> float:
    """Linear percent of pace: 105% is 5% less time/km, 90% is 10% more."""
    return base_s_per_km * (2.0 - pct / 100.0)


def fmt(sec_per_km: float) -> str:
    return f"{int(sec_per_km // 60)}:{int(round(sec_per_km % 60)):02d}/km"


def derive_base(args) -> tuple[float, str]:
    if args.base:
        s = vdot.parse_time(args.base)
        return s, f"base pace given directly ({args.base}/km)"
    if args.tenk:
        t = vdot.parse_time(args.tenk)
        return t / 10.0, f"10k time {args.tenk}"
    # fall back to current fitness from data (same anchor logic as paces.py)
    import paces

    ns = argparse.Namespace(vdot=None, race=None)
    v, source = paces.derive_vdot(ns)
    t = vdot.race_time(v, 10000)
    return t / 10.0, f"current fitness (VDOT {v:.1f}, 10k eq {vdot.time_str(t)}; {source})"


def main():
    parser = argparse.ArgumentParser(description="Percent-of-speed paces (RunningWritings)")
    parser.add_argument("--tenk", help="anchor 10k time, e.g. 53:42")
    parser.add_argument("--base", help="anchor base pace per km, e.g. 5:24")
    parser.add_argument("pcts", nargs="*", type=float, help="percentages (default: standard zones)")
    args = parser.parse_args()

    base, source = derive_base(args)
    zones = [(p, "") for p in args.pcts] if args.pcts else STANDARD_ZONES

    print("=" * 62)
    print(f"Base 10k pace {fmt(base)}  ({source})")
    print("linear percent-of-pace convention: target = base * (2 - pct/100)")
    print("=" * 62)
    rows = {}
    for pct, label in zones:
        pace = pace_at_percent(base, pct)
        rows[f"{pct:g}%"] = fmt(pace)
        print(f"  {pct:>5g}%  {fmt(pace):>9}   {label}")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "calculated_at": datetime.now().isoformat(timespec="seconds"),
        "convention": "linear percent of pace: target = base_pace * (2 - pct/100)",
        "base_pace_s_per_km": round(base, 1),
        "anchor": source,
        "paces": rows,
    }
    out = HISTORY_DIR / f"percent-{datetime.now().date().isoformat()}.json"
    out.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
