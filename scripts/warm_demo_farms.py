"""Warm the two demo plots of the Chira valley before a demo.

Calls the app endpoints with the same bodies the app sends by default, so
both the upstream caches (NASA POWER, SoilGrids, Open-Meteo) and the
last-good copies are filled. Run it the same day as the demo: the app
sends today's date as the planting date.

    python scripts/warm_demo_farms.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date

import httpx

DEMO_FARMS = {
    "Marcavelica (margen norte del Chira, frente a Sullana)": (-4.865, -80.72),
    "Amotape (Chira bajo)": (-4.88, -81.02),
}


def _call(client: httpx.Client, method: str, path: str, **kwargs: object) -> str:
    started = time.monotonic()
    response = client.request(method, path, **kwargs)
    elapsed = time.monotonic() - started
    served = response.headers.get("X-Served-From", "-")
    return f"{response.status_code} en {elapsed:.1f} s ({served})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    failed = False
    with httpx.Client(base_url=args.base_url, timeout=300) as client:
        print("catalog:", _call(client, "GET", "/api/v1/app/catalog"))
        for name, (lat, lon) in DEMO_FARMS.items():
            print(f"== {name} ({lat}, {lon})")
            result = _call(
                client, "GET", "/api/v1/app/climate-overview", params={"lat": lat, "lon": lon}
            )
            print("  clima:", result)
            failed |= not result.startswith("200")
            base = {
                "lat": lat,
                "lon": lon,
                "area_ha": 1.0,
                "planting_date": date.today().isoformat(),
                "consecutive_campaigns": 1,
            }
            for label, body in (
                ("recomendación", base),
                ("recomendación, último cultivo arroz", {**base, "last_crop_id": "rice"}),
            ):
                result = _call(client, "POST", "/api/v1/app/recommendation", json=body)
                print(f"  {label}:", result)
                failed |= not result.startswith("200")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
