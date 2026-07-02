"""Training pace calculator anchored to CURRENT fitness.

Derives a VDOT and prints Daniels training paces (E/M/T/I/R), equivalent race
times, and heart-rate zones. Anchor priority:

  1. --vdot 42            explicit override
  2. --race 10k 52:30     a race not yet in config.json
  3. config.json          best race within the last 90 days
  4. synced data          best measured 3k+ rolling effort in the last 8 weeks
                          (falls back to Garmin's race predictor if no streams)

Usage:
    python scripts/paces.py
    python scripts/paces.py --race 10k 52:30
    python scripts/paces.py --vdot 42
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import vdot

HISTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "paces_history"


def derive_vdot(args) -> tuple[float, str]:
    if args.vdot:
        return args.vdot, f"manual override (--vdot {args.vdot})"
    if args.race:
        dist_text, time_text = args.race
        d = vdot.parse_distance(dist_text)
        t = vdot.parse_time(time_text)
        v = vdot.vdot_from_race(d, t)
        return v, f"race result: {dist_text} in {time_text}"

    # fall back to config races, then synced data
    import analyze

    recent_races = [
        r for r in analyze.config_races()
        if (datetime.now() - r["dt"]).days <= analyze.RECENT_RACE_DAYS
    ]
    if recent_races:
        best = max(recent_races, key=lambda r: r["vdot"])
        return best["vdot"], (
            f"race: {best['event']} on {best['dt'].date()}, "
            f"{int(best['distance_m'])}m in {vdot.time_str(best['time_s'])}"
        )

    try:
        df = analyze.load_index()
        bests = analyze.recent_best_efforts(df)
        max_hr_ref = analyze.athlete_setting("max_hr") or analyze.observed_max_hr(df)
    except SystemExit:
        bests, max_hr_ref = {}, None
    race_worthy = analyze.race_worthy_efforts(bests, max_hr_ref)
    if race_worthy:
        target, best = max(race_worthy.items(), key=lambda kv: kv[1]["vdot"])
        return best["vdot"], (
            f"measured best effort: {target}m in {vdot.time_str(best['time_s'])} "
            f"on {best['date']} (training run, slightly conservative)"
        )
    preds = analyze.garmin_predictions(analyze.load_physiology())
    if preds.get("10k"):
        v = vdot.vdot_from_race(vdot.DISTANCES_M["10k"], preds["10k"])
        return v, "Garmin race predictor (tends optimistic - treat paces as a ceiling)"
    raise SystemExit(
        "No anchor available. Run scripts/sync.py, add a race to config.json, "
        "or pass --race DIST TIME (e.g. --race 10k 52:30)"
    )


def print_hr_zones() -> None:
    import analyze

    physio = analyze.load_physiology()
    lthr = analyze.athlete_setting("lactate_threshold_hr")
    lthr_src = "config"
    if not lthr:
        lthr = analyze.find_key(
            physio.get("lactate_threshold"), {"heartrate", "lactatethresholdheartrate"}
        )
        lthr_src = "Garmin"
    max_hr = analyze.athlete_setting("max_hr")
    max_src = "config"
    if not max_hr:
        try:
            max_hr = analyze.observed_max_hr(analyze.load_index())
            max_src = "observed in runs"
        except SystemExit:
            max_hr = None

    if lthr:
        print(f"\nHR zones from lactate threshold HR ({int(lthr)} bpm, {lthr_src}):")
        zones = [
            ("E  easy/recovery", 0.70, 0.88),
            ("M  steady",        0.89, 0.93),
            ("T  threshold",     0.94, 1.00),
            ("I  interval",      1.01, 1.05),
        ]
        for name, lo, hi in zones:
            print(f"  {name:<18} {int(lthr * lo)}-{int(lthr * hi)} bpm")
    if max_hr:
        print(f"\nHR zones from max HR ({int(max_hr)} bpm, {max_src}; Daniels %HRmax):")
        zones = [
            ("E  easy/recovery", 0.65, 0.79),
            ("M  marathon",      0.80, 0.90),
            ("T  threshold",     0.88, 0.92),
            ("I  interval",      0.98, 1.00),
        ]
        for name, lo, hi in zones:
            print(f"  {name:<18} {int(max_hr * lo)}-{int(max_hr * hi)} bpm")
    if not lthr and not max_hr:
        print("\n(no HR data synced yet - run sync.py to get HR zones)")


def split_str(v_m_per_min: float, meters: float) -> str:
    return vdot.time_str(meters / v_m_per_min * 60)


def main():
    parser = argparse.ArgumentParser(description="Daniels training paces from current fitness")
    parser.add_argument("--race", nargs=2, metavar=("DIST", "TIME"),
                        help="recent race, e.g. --race 10k 52:30")
    parser.add_argument("--vdot", type=float, help="explicit VDOT")
    args = parser.parse_args()

    v, source = derive_vdot(args)
    paces = vdot.training_paces(v)

    print("=" * 62)
    print(f"VDOT {v:.1f}  (anchor: {source})")
    print("=" * 62)

    e_lo, e_hi = paces["E"]
    print("\nTraining paces:")
    print(f"  E  easy        {vdot.pace_str(e_lo)} - {vdot.pace_str(e_hi)}")
    print(f"  M  marathon    {vdot.pace_str(paces['M'])}")
    print(f"  T  threshold   {vdot.pace_str(paces['T'])}   "
          f"({split_str(paces['T'], 400)}/400m, {split_str(paces['T'], 1000)}/km)")
    print(f"  I  interval    {vdot.pace_str(paces['I'])}   "
          f"({split_str(paces['I'], 400)}/400m, {split_str(paces['I'], 1000)}/km)")
    print(f"  R  repetition  {vdot.pace_str(paces['R'])}   "
          f"({split_str(paces['R'], 200)}/200m, {split_str(paces['R'], 400)}/400m)")

    race_times = {}
    print("\nEquivalent race times at this fitness:")
    for label in ("5k", "10k", "half", "marathon"):
        t = vdot.race_time(v, vdot.DISTANCES_M[label])
        race_times[label] = vdot.time_str(t)
        print(f"  {label:>9}: {vdot.time_str(t)}")

    print_hr_zones()

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "calculated_at": datetime.now().isoformat(timespec="seconds"),
        "vdot": round(v, 1),
        "anchor": source,
        "training_paces": {
            "E": f"{vdot.pace_str(e_lo)} - {vdot.pace_str(e_hi)}",
            "M": vdot.pace_str(paces["M"]),
            "T": vdot.pace_str(paces["T"]),
            "I": vdot.pace_str(paces["I"]),
            "R": vdot.pace_str(paces["R"]),
        },
        "equivalent_race_times": race_times,
    }
    out = HISTORY_DIR / f"vdot-{datetime.now().date().isoformat()}.json"
    out.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
