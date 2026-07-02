"""Jack Daniels VDOT math.

Two published equations drive everything:
  vo2_at_velocity(v): oxygen cost of running at velocity v (m/min)
  fraction_vo2max(t): fraction of VO2max sustainable for a race lasting t minutes

VDOT of a performance = vo2_at_velocity(d/t) / fraction_vo2max(t).
Training paces are velocities at fixed fractions of VDOT (Daniels' intensities).
"""

import math

DISTANCES_M = {
    "1500": 1500,
    "1mi": 1609.34,
    "3k": 3000,
    "5k": 5000,
    "10k": 10000,
    "half": 21097.5,
    "marathon": 42195,
}


def vo2_at_velocity(v: float) -> float:
    """Oxygen cost (ml/kg/min) of running at v m/min."""
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def fraction_vo2max(t_min: float) -> float:
    """Fraction of VO2max sustainable for a maximal effort lasting t_min minutes."""
    return (
        0.8
        + 0.1894393 * math.exp(-0.012778 * t_min)
        + 0.2989558 * math.exp(-0.1932605 * t_min)
    )


def vdot_from_race(distance_m: float, time_s: float) -> float:
    t_min = time_s / 60.0
    v = distance_m / t_min
    return vo2_at_velocity(v) / fraction_vo2max(t_min)


def velocity_at_fraction(vdot: float, p: float) -> float:
    """Velocity (m/min) whose oxygen cost equals p * VDOT (invert the quadratic)."""
    c = 4.60 + p * vdot
    return (-0.182258 + math.sqrt(0.182258**2 + 4 * 0.000104 * c)) / (2 * 0.000104)


def race_time(vdot: float, distance_m: float) -> float:
    """Predicted race time in seconds at a given VDOT, solved by bisection on t."""
    lo, hi = 1.0, 600.0  # minutes
    for _ in range(80):
        mid = (lo + hi) / 2
        implied = vo2_at_velocity(distance_m / mid) / fraction_vo2max(mid)
        if implied > vdot:  # running that fast needs more fitness -> slow down
            lo = mid
        else:
            hi = mid
    return mid * 60.0


def pace_str(v_m_per_min: float) -> str:
    """Velocity in m/min -> 'M:SS/km'."""
    sec_per_km = 60000.0 / v_m_per_min
    return f"{int(sec_per_km // 60)}:{int(round(sec_per_km % 60)):02d}/km"


def time_str(seconds: float) -> str:
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def training_paces(vdot: float) -> dict:
    """Daniels training intensities.

    E uses 59-74% VDOT; M is true marathon race pace at this VDOT; T is the
    velocity sustainable for a ~60-minute race; I is at 100% VDOT (vVO2max,
    a ~11-minute race); R is ~107% (matches Daniels' published R tables).
    """
    m_time = race_time(vdot, DISTANCES_M["marathon"])
    m_vel = DISTANCES_M["marathon"] / (m_time / 60.0)
    i_vel = velocity_at_fraction(vdot, 1.00)
    r_vel = velocity_at_fraction(vdot, 1.07)
    return {
        "E": (velocity_at_fraction(vdot, 0.59), velocity_at_fraction(vdot, 0.74)),
        "M": m_vel,
        "T": velocity_at_fraction(vdot, fraction_vo2max(60.0)),
        "I": i_vel,
        "R": r_vel,
    }


def parse_time(text: str) -> float:
    """'52:30' or '1:52:30' or '4:05' -> seconds."""
    parts = [float(p) for p in text.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def parse_distance(text: str) -> float:
    """'10k', 'half', '5000', '5000m' -> meters."""
    key = text.lower().strip()
    if key in DISTANCES_M:
        return DISTANCES_M[key]
    return float(key.rstrip("m"))
