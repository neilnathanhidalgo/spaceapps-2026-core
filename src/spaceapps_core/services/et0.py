"""Reference evapotranspiration (ET0) from temperature only.

Hargreaves-Samani, the FAO-56 fallback when radiation, humidity and wind are
not available: it only needs daily maximum and minimum temperature plus the
extraterrestrial radiation, which depends on latitude and day of the year.

`reference_et0` is isolated on purpose so a better method (Penman-Monteith
with POWER radiation and wind) can replace it without touching the engine.
"""

from __future__ import annotations

import math

SOLAR_CONSTANT_MJ = 0.0820
MINUTES_PER_DAY = 24 * 60
MJ_TO_MM = 0.408
HARGREAVES_COEFFICIENT = 0.0023
HARGREAVES_OFFSET_C = 17.8
DAYS_IN_YEAR = 365


def extraterrestrial_radiation(latitude: float, day_of_year: int) -> float:
    """Radiation at the top of the atmosphere, in MJ/m²/day (FAO-56 eq. 21)."""

    phi = math.radians(latitude)
    relative_distance = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / DAYS_IN_YEAR)
    declination = 0.409 * math.sin(2 * math.pi * day_of_year / DAYS_IN_YEAR - 1.39)
    # Beyond the polar circles the sun never sets (or never rises) and the
    # formula's argument leaves [-1, 1].
    sunset_angle = math.acos(_clamp(-math.tan(phi) * math.tan(declination)))
    return (
        MINUTES_PER_DAY
        / math.pi
        * SOLAR_CONSTANT_MJ
        * relative_distance
        * (
            sunset_angle * math.sin(phi) * math.sin(declination)
            + math.cos(phi) * math.cos(declination) * math.sin(sunset_angle)
        )
    )


def reference_et0(
    *,
    t2m_max: float,
    t2m_min: float,
    latitude: float,
    day_of_year: int,
) -> float:
    """Daily reference evapotranspiration in mm/day (Hargreaves-Samani)."""

    radiation_mm = MJ_TO_MM * extraterrestrial_radiation(latitude, day_of_year)
    mean = (t2m_max + t2m_min) / 2
    spread = math.sqrt(max(t2m_max - t2m_min, 0.0))
    return max(HARGREAVES_COEFFICIENT * radiation_mm * (mean + HARGREAVES_OFFSET_C) * spread, 0.0)


def _clamp(value: float) -> float:
    return min(max(value, -1.0), 1.0)
