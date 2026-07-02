# Percentage-based 10k training (Full-Spectrum plan system)

Sources:
- John Davis, "Percentage-based training for the 10k", runningwritings.com/2024/10/percentage-based-10k-training.html (added 2026-07-02)
- Pace calculator: apps.runningwritings.com/pace-percent (percent-of-SPEED convention)

This is the system behind the plan Ben is executing:
`plans/Full-Spectrum-10k-Schedule-16-weeks-metric-from-RunningWritings.pdf`.

## THE convention (use for every pace calculation)
Percentages apply **linearly to PACE, symmetric around 100%** (Canova-style;
verified against apps.runningwritings.com/pace-percent):

    target pace = base 10k pace * (2 - pct / 100)

Each 10% step is the same pace increment ("90% of 5:00/mi is 5:30, 80% is
6:00 - each 10% jump is 30 s/mi"). E.g. base 5:24/km: 90% -> 5:56/km,
95% -> 5:40/km, 105% -> 5:08/km. NOT percent-of-speed (base/(pct/100)) -
research papers use that, coaching practice doesn't. 100% = current-estimate
10k race pace; >100% faster, <100% slower. Anchor to CURRENT 10k fitness,
not goal time; re-estimate every 2-4 weeks from how 90-105% workouts feel
(they're the "hardest to cheat on").

## Pace zones (% of 10k speed)
| Zone | % | Use |
|---|---|---|
| Very easy | 45-55 | recovery, doubles |
| Easy | 55-65 | general aerobic volume |
| Moderate | 70-80 | transition stimulus |
| Long fast / strong | 80-85(-90) | long runs with quality |
| 10k-supportive endurance | 90 | continuous long runs |
| Sub-threshold (double-T) | 91-93 | longer repeats |
| 10k-specific endurance | 95 | 6-13 km continuous |
| Classical lactate threshold | 96-97 | cruise intervals |
| Supra-threshold | 99-101 | short near-race repeats |
| 10k race pace | 100 | the core specific workouts |
| 10k-specific speed (~5k pace) | 105 | 1k-2k reps |
| 10k-supportive speed | 110 | 400-800m reps |
| 3k/1500 pace | ~115 | rare, mixed pyramids |
| Strides | 85-95% *effort* | 5-6 x 100m, 2-3x/week |
| Hill sprints | max | 5-6 x 10s |

Rule: don't mix speeds >5% apart in one workout (100+105 ok, 100+115 not) —
mixed-speed sessions dilute the stimulus.

## 16-week plan structure
1. **General (wk 1-6)**: volume builds, long easy runs (~19-24 km), moderate
   runs, light fartlek (8-10 x 2min at 105%, or 3-2-1min cutdowns 100-108%).
   First 10k-pace workout already in week 2 (8 x 1000m at 100% w/ 2min jog).
   Progress a workout every 10-14 days (more volume or longer reps).
2. **Race-supportive (wk 7-10)**: mileage peaks. 90% continuous runs,
   95% continuous progression (6 -> 13 km), threshold cruise intervals with
   float recoveries (6 x 1200m at 96-97% w/ 1min jog -> 400m floats at 80-85%),
   alternations (6-7 x [1k at 95% + 1k at 80-85%]).
3. **Race-specific (wk 11-15)**: intensity over volume (mileage may drop).
   Stepping stones every 10-14 days: 4-5 x 2k at 100% w/ 3min jog;
   8 x 1k at 100%; 4 x (1200m at 100% + 800m at 103-105%).
   Final big session 10-14 days out: 3-2-2-1k at 100/101/102/105-107%.
4. **Taper (wk 16)**: big mileage cut, keep short race-pace touches + strides.

Weekly shape: one quality session per day max, never the same pace twice in a
week; 1 easy day between workouts in general phase, 2-3 in specific phases;
long-run day fixed; doubles optional and always very easy (45-55%).

## Scaling down (relevant to Ben's rebuild)
- Cut/skip doubles; convert moderate runs to easy; strides or hill sprints
  2x/week instead of evening speed sessions; no double-threshold days.
- Reduce 85-95% volume and 105-110% volume ~10% each.
- Shorten race-specific phase to 4 weeks, extend general phase, if needed.
- **Keep the minimum: ~8 km of work at 100% in the final race-specific
  session** — the 10k is 10 km for everyone.
- Mileage serves the workouts, not the other way around; dropping peak
  mileage (e.g. 75 -> 65) is fine if aerobic base was built before.

## Execution realism
- Expect to complete only ~80% of planned workouts; that's normal.
- One bad workout in a progression means nothing; several at the same pace
  means the 10k estimate is too fast — re-anchor down.
- Rebuild the plan from scratch whenever reality changes (illness, travel,
  breakthrough) rather than forcing the original schedule.
- Races can replace workouts: 5k race = 105% session, 8k/10k = 100%,
  15k-20k = 95%, half marathon = 90%.
- Easy pace precision doesn't matter; when in doubt, easier.

Cross-refs: session spacing & easy/hard separation in
[intensity-discipline.md](intensity-discipline.md); volume progression &
comeback rules in
[load-management-and-injury-prevention.md](load-management-and-injury-prevention.md).
