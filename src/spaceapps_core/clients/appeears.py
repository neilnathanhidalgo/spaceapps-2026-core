from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ..core.cache import get_cache
from ..core.config import get_settings
from ..core.errors import NotConfiguredError, UpstreamError
from ..core.http import async_client, request_with_retry
from ..schemas.common import Location, TimePoint, TimeSeries
from ..schemas.variables import CANONICAL_VARIABLES, CanonicalVariable
from .base import BaseClient

APPEEARS_BASE_URL = "https://appeears.earthdatacloud.nasa.gov/api"
TOKEN_CACHE_KEY = "appeears:token"


@dataclass
class AppEEARSLayer:
    """A single AppEEARS product/layer selection."""

    product: str
    layer: str
    canonical: CanonicalVariable

    def column_name(self) -> str:
        return f"{self.product.replace('.', '_')}_{self.layer}"


class AppEEARSClient(BaseClient):
    """AppEEARS asynchronous point/area extraction client.

    Documentation: https://appeears.earthdatacloud.nasa.gov/api/
    Requires NASA Earthdata credentials (EARTHDATA_USERNAME/PASSWORD).
    """

    source_name = "appeears"
    token_ttl_seconds = 36 * 60 * 60  # tokens live ~48 h; refresh at 36 h.

    def __init__(
        self,
        *,
        base_url: str = APPEEARS_BASE_URL,
        timeout: float | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._settings = get_settings()

    def _ensure_credentials(self) -> tuple[str, str]:
        if not self._settings.earthdata_configured:
            raise NotConfiguredError("AppEEARS requires EARTHDATA_USERNAME and EARTHDATA_PASSWORD.")
        return self._settings.earthdata_username, self._settings.earthdata_password

    async def login(self, *, force: bool = False) -> str:
        """Return a bearer token, caching it on disk."""

        cache = get_cache()
        if not force:
            token = cache.get(TOKEN_CACHE_KEY)
            if token:
                return str(token)

        user, pw = self._ensure_credentials()
        async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
            r = await request_with_retry(
                c,
                "POST",
                "/login",
                auth=(user, pw),
                headers={"Content-Length": "0"},
            )
        if r.status_code != 200:
            raise UpstreamError(f"AppEEARS login failed with HTTP {r.status_code}: {r.text[:200]}")
        token = r.json().get("token")
        if not token:
            raise UpstreamError("AppEEARS login response did not include a token.")
        cache.set(TOKEN_CACHE_KEY, token, expire=self.token_ttl_seconds)
        return str(token)

    async def submit_point_task(
        self,
        *,
        location: Location,
        start: date,
        end: date,
        layers: list[AppEEARSLayer],
        task_name: str | None = None,
    ) -> str:
        token = await self.login()
        body = {
            "task_type": "point",
            "task_name": task_name or f"spaceapps-{int(time.time())}",
            "params": {
                "dates": [
                    {
                        "startDate": start.strftime("%m-%d-%Y"),
                        "endDate": end.strftime("%m-%d-%Y"),
                    }
                ],
                "layers": [{"product": layer.product, "layer": layer.layer} for layer in layers],
                "coordinates": [{"latitude": location.lat, "longitude": location.lon, "id": "0"}],
            },
        }
        async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
            r = await request_with_retry(
                c,
                "POST",
                "/task",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
        if r.status_code >= 400:
            raise UpstreamError(f"AppEEARS task submit failed HTTP {r.status_code}: {r.text[:200]}")
        task_id = r.json().get("task_id")
        if not task_id:
            raise UpstreamError("AppEEARS task submit response did not include task_id.")
        return str(task_id)

    async def get_task(self, task_id: str) -> dict[str, Any]:
        token = await self.login()
        async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
            r = await request_with_retry(
                c,
                "GET",
                f"/task/{task_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code == 404:
            raise UpstreamError(f"AppEEARS task {task_id} not found.")
        if r.status_code >= 400:
            raise UpstreamError(f"AppEEARS get task failed HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    async def list_bundle(self, task_id: str) -> list[dict[str, Any]]:
        token = await self.login()
        async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
            r = await request_with_retry(
                c,
                "GET",
                f"/bundle/{task_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code >= 400:
            raise UpstreamError(
                f"AppEEARS bundle listing failed HTTP {r.status_code}: {r.text[:200]}"
            )
        data = r.json()
        return list(data.get("files", []))

    async def download_file(self, task_id: str, file_id: str) -> bytes:
        token = await self.login()
        async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
            r = await request_with_retry(
                c,
                "GET",
                f"/bundle/{task_id}/{file_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code >= 400:
            raise UpstreamError(f"AppEEARS file download failed HTTP {r.status_code}.")
        return r.content

    @staticmethod
    def parse_point_csv(
        csv_bytes: bytes,
        layers: list[AppEEARSLayer],
        location: Location,
    ) -> list[TimeSeries]:
        """Parse an AppEEARS point-task results CSV into TimeSeries.

        The CSV has one row per date; columns include at least an ISO date and a column
        per requested layer named ``<PRODUCT_VERSION>_<LAYER>`` (dots replaced by
        underscores).
        """
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))

        date_field = next(
            (f for f in (reader.fieldnames or []) if f.lower() in {"date", "datetime"}),
            None,
        )
        if date_field is None:
            raise UpstreamError("AppEEARS CSV has no recognizable date column.")

        rows_by_layer: dict[str, list[TimePoint]] = {layer.column_name(): [] for layer in layers}
        for row in reader:
            iso = row.get(date_field, "").strip()
            try:
                parsed = datetime.fromisoformat(iso).date()
            except ValueError:
                try:
                    parsed = datetime.strptime(iso, "%Y-%m-%d").date()
                except ValueError:
                    continue
            for layer in layers:
                col = layer.column_name()
                raw = row.get(col)
                if raw is None or raw == "" or raw.lower() == "nan":
                    rows_by_layer[col].append(TimePoint(date=parsed, value=None))
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    value = None
                rows_by_layer[col].append(TimePoint(date=parsed, value=value))

        series: list[TimeSeries] = []
        for layer in layers:
            series.append(
                TimeSeries(
                    source="appeears",
                    variable=layer.canonical,
                    unit=CANONICAL_VARIABLES[layer.canonical].unit,
                    location=location,
                    temporal_resolution="daily",
                    points=rows_by_layer[layer.column_name()],
                    metadata={
                        "product": layer.product,
                        "layer": layer.layer,
                        "api": "appeears",
                    },
                )
            )
        return series


MODIS_NDVI_LAYERS = [
    AppEEARSLayer(
        product="MOD13Q1.061",
        layer="_250m_16_days_NDVI",
        canonical=CanonicalVariable.NDVI,
    ),
    AppEEARSLayer(
        product="MOD13Q1.061",
        layer="_250m_16_days_EVI",
        canonical=CanonicalVariable.EVI,
    ),
]

SMAP_SOIL_MOISTURE_LAYERS = [
    AppEEARSLayer(
        product="SPL3SMP_E.006",
        layer="Soil_Moisture_Retrieval_Data_AM_soil_moisture",
        canonical=CanonicalVariable.SOIL_MOISTURE,
    ),
]
