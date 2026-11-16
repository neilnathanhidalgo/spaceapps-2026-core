"""Would Semi have warned about the 2024-2025 water shortage in the Chira?

Runs the water indicator and the recommendation for a rice plot of the
Chira valley with NASA POWER data only up to 31 October 2024 (`--as-of
2024-11-01`), and prints the result as it comes out. Nothing is tuned: the
indicator rule is fixed in `services/water_availability.py`.

    python scripts/validate_drought_2024.py [--lat -4.865 --lon -80.72] [--as-of 2024-11-01]

It runs both water indicators: rain and soil of the plot's zone, and rain of
the last rainy season in the upper Chira-Catamayo basin, as an approximation
of the water that arrives through irrigation from Poechos. The second one is
an approximation with rain, not the real level of the reservoir. NASA POWER
cells are about 0.5 x 0.625 degrees.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from spaceapps_core.schemas.common import Location
from spaceapps_core.schemas.recommendation import RecommendationRequest
from spaceapps_core.services.agro_config import load_agro_config
from spaceapps_core.services.irrigation_water import fetch_irrigation_water
from spaceapps_core.services.local_soil import fetch_soil_profile
from spaceapps_core.services.recommendation import (
    build_recommendation,
    fetch_scenario_climates,
    least_water_level,
)
from spaceapps_core.services.water_availability import fetch_water_availability

LEVELS = {"low": "BAJO", "medium": "MEDIO", "high": "ALTO"}


async def run(lat: float, lon: float, as_of: date) -> None:
    config = load_agro_config()
    location = Location(lat=lat, lon=lon)
    water, irrigation, climates, soil = await asyncio.gather(
        fetch_water_availability(location, as_of),
        fetch_irrigation_water(as_of),
        fetch_scenario_climates(location, config.scenarios),
        fetch_soil_profile(location, config.thresholds),
    )
    request = RecommendationRequest(
        lat=lat,
        lon=lon,
        area_ha=1.0,
        planting_date=date(as_of.year, 12, 15),
        last_crop_id="rice",
        consecutive_campaigns=3,
    )
    with_water = build_recommendation(
        request, config, climates, soil=soil, water=water, irrigation=irrigation
    )
    without_water = build_recommendation(request, config, climates, soil=soil)
    names = {crop.id: crop.name for crop in config.crops}

    def label(option_id: str) -> str:
        option = next(o for o in with_water.options if o.id == option_id)
        return " > ".join(names[crop_id] for crop_id in option.crop_ids)

    print(f"Chacra arrocera del Chira ({lat}, {lon}); datos de NASA POWER hasta {as_of} (excluido)")
    if water is None:
        print("Indicador de agua: SIN DATOS (NASA POWER no tiene la ventana completa).")
        return
    print(
        f"Ventana {water.window_start} a {water.window_end}; referencia {water.reference_years[0]}-"
        f"{water.reference_years[-1]}"
    )
    print(
        f"  Lluvia: {water.rain_mm} mm (normal {water.rain_normal_mm} mm), "
        f"percentil {water.rain_percentile}"
    )
    print(
        f"  Humedad raíces: {water.root_wetness} (normal {water.root_wetness_normal}), "
        f"percentil {water.root_wetness_percentile}"
    )
    print(f"  Nivel: {LEVELS[water.level]}. Semi diría: {water.finding}")
    print("Agua que llega por riego (lluvia de la cuenca alta, aproximación):")
    if irrigation is None:
        print("  SIN DATOS (NASA POWER no tiene la temporada completa).")
    else:
        print(
            f"  Temporada {irrigation.season_start} a {irrigation.season_end}: "
            f"{irrigation.rain_mm} mm (normal {irrigation.rain_normal_mm} mm, "
            f"{irrigation.percent_vs_normal:+.0f} %), percentil {irrigation.rain_percentile}"
        )
        for point in irrigation.points:
            print(f"    {point.name}: {point.rain_mm} mm (normal {point.rain_normal_mm} mm)")
        print(f"  Nivel: {LEVELS[irrigation.level]}. Semi diría: {irrigation.finding}")
    worst = least_water_level(water, irrigation)
    print(f"Para el orden de las rotaciones cuenta el más desfavorable: {LEVELS[worst]}")
    print("Orden de las rotaciones (escenario normal):")
    for priority in config.priorities:
        before = without_water.ranking[priority.id]["normal"]
        after = with_water.ranking[priority.id]["normal"]
        moved = "" if before == after else f"  (sin el indicador: {', '.join(before)})"
        print(f"  {priority.name}: {', '.join(after)}{moved}")
    for option in with_water.options:
        print(f"  {option.id} = {label(option.id)}")
    practice = with_water.current_practice.scenarios["normal"]
    best = with_water.options[0].scenarios["normal"]
    print(
        f"Seguir con arroz: {practice.irrigation_m3:,.0f} m³/ha en un año normal; "
        f"la opción r1 pide {best.irrigation_m3:,.0f} m³/ha."
    )
    print()
    irrigation_level = LEVELS[irrigation.level] if irrigation else "SIN DATOS"
    irrigation_text = irrigation.finding if irrigation else "sin datos de la cuenca alta."
    print("Resumen en tres líneas:")
    print(
        f"1. Con datos de NASA POWER hasta {as_of:%d/%m/%Y} (excluido): lluvia y tierra de "
        f"la zona {LEVELS[water.level]}; agua que llega por riego {irrigation_level}."
    )
    print(f"2. {water.finding} {irrigation_text}")
    if worst == "low":
        print(
            "3. Semi habría puesto al final las rotaciones con cultivos de mucha agua "
            "antes de la siembra de 2025."
        )
    else:
        print(
            "3. Semi NO habría advertido la falta de agua de inicios de 2025 con datos "
            "hasta esa fecha: ningún indicador salía BAJO."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lat", type=float, default=-4.865)
    parser.add_argument("--lon", type=float, default=-80.72)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2024, 11, 1))
    args = parser.parse_args()
    asyncio.run(run(args.lat, args.lon, args.as_of))


if __name__ == "__main__":
    main()
