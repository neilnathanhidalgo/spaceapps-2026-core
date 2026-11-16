"""Would Semi have warned about the 2024-2025 water shortage in the Chira?

Runs the water indicator and the recommendation for a rice plot of the
Chira valley with NASA POWER data only up to 31 October 2024 (`--as-of
2024-11-01`), and prints the result as it comes out. Nothing is tuned: the
indicator rule is fixed in `services/water_availability.py`.

    python scripts/validate_drought_2024.py [--lat -4.865 --lon -80.72] [--as-of 2024-11-01]

Note: NASA POWER cells are about 0.5 x 0.625 degrees, so the indicator
describes the zone, not the single plot. Irrigation in the Chira comes from
the Poechos reservoir, whose inflow depends on rain upstream (Chira-Catamayo
basin), which this point-based indicator does not see.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from spaceapps_core.schemas.common import Location
from spaceapps_core.schemas.recommendation import RecommendationRequest
from spaceapps_core.services.agro_config import load_agro_config
from spaceapps_core.services.local_soil import fetch_soil_profile
from spaceapps_core.services.recommendation import build_recommendation, fetch_scenario_climates
from spaceapps_core.services.water_availability import fetch_water_availability

LEVELS = {"low": "BAJO", "medium": "MEDIO", "high": "ALTO"}


async def run(lat: float, lon: float, as_of: date) -> None:
    config = load_agro_config()
    location = Location(lat=lat, lon=lon)
    water, climates, soil = await asyncio.gather(
        fetch_water_availability(location, as_of),
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
    with_water = build_recommendation(request, config, climates, soil=soil, water=water)
    without_water = build_recommendation(request, config, climates, soil=soil, water=None)
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
    print("Resumen en tres líneas:")
    print(
        f"1. Con datos de NASA POWER hasta octubre de 2024, el semáforo de agua de la zona "
        f"salía {LEVELS[water.level]}."
    )
    print(f"2. {water.finding}")
    if water.level == "low":
        print(
            "3. Semi habría puesto al final las rotaciones con cultivos de mucha agua: "
            "la advertencia llegaba antes de la siembra de 2025."
        )
    else:
        print(
            "3. Semi NO habría advertido la falta de agua de inicios de 2025: este "
            "indicador mide la lluvia y la tierra de la zona, no el agua guardada en "
            "Poechos, que es la que riega el Chira."
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
