# API Reference

Reference for every endpoint exposed by `spaceapps-2026-core`.
Generated from the code in `src/spaceapps_core/`.

- Base prefix: `/api/v1` (health endpoints live at the root).
- Every data endpoint accepts `format=json|csv|parquet` when it returns time
  series. `csv` → `text/csv`, `parquet` → `application/octet-stream`.
- Dates use ISO format (`YYYY-MM-DD`).
- Coordinates are validated: `lat ∈ [-90, 90]`, `lon ∈ [-180, 180]`.

## Index

- [Common schemas](#common-schemas)
- [Canonical variables](#canonical-variables)
- [Health](#health)
  - `GET /health`
  - `GET /health/sources`
- [Climate](#climate)
  - `GET /api/v1/climate/history`
  - `GET /api/v1/climate/forecast`
- [Precipitation](#precipitation)
  - `GET /api/v1/precipitation`
- [Vegetation (async)](#vegetation)
  - `POST /api/v1/vegetation/jobs`
- [Soil moisture (async)](#soil-moisture)
  - `POST /api/v1/soil-moisture/jobs`
- [Jobs](#jobs)
  - `GET /api/v1/jobs/{job_id}`
- [Climate projections](#climate-projections)
  - `GET /api/v1/projections`
- [Sentinel-2](#sentinel-2)
  - `GET /api/v1/sentinel-2/scenes`
- [Features (multi-source table)](#features-multi-source-table)
  - `GET /api/v1/features`

---

## Common schemas

### `Location`
| Field | Type | Notes |
|---|---|---|
| `lat` | `float` | `-90..90` |
| `lon` | `float` | `-180..180` |
| `geometry` | `object \| null` | Optional GeoJSON (Polygon/MultiPolygon) |

### `TimePoint`
| Field | Type | Notes |
|---|---|---|
| `date` | `date` (`YYYY-MM-DD`) | |
| `value` | `float \| null` | `null` = missing / NaN |

### `TimeSeries`
The unified shape returned by **every** data client.

| Field | Type | Notes |
|---|---|---|
| `source` | `string` | `power`, `open_meteo`, `appeears`, `earthdata`, `nex_gddp` |
| `variable` | `CanonicalVariable` | see table below |
| `unit` | `string` | e.g. `degC`, `mm/day`, `%`, `m/s`, `index`, `m^3/m^3`, `MJ/m^2/day` |
| `location` | `Location` | |
| `temporal_resolution` | `"daily" \| "hourly" \| "monthly" \| "climatology"` | currently almost always `daily` |
| `points` | `TimePoint[]` | sorted by date |
| `metadata` | `object` | source-specific (see each endpoint) |
| `retrieved_at` | `datetime` (UTC) | response timestamp |

### `JobStatus`
| Field | Type | Notes |
|---|---|---|
| `id` | `string` | AppEEARS task id |
| `source` | `string` | `appeears_modis` or `appeears_smap` |
| `status` | `"pending" \| "queued" \| "running" \| "done" \| "failed"` | mapped from AppEEARS |
| `progress` | `float \| null` | `0..1` |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | |
| `message` | `string \| null` | raw upstream status |

### `JobResult`
| Field | Type | Notes |
|---|---|---|
| `id` | `string` | |
| `status` | `JobStatus` | |
| `series` | `TimeSeries[]` | empty until status is `done` |
| `raw` | `object \| null` | reserved for debugging |

### `ErrorResponse`
Every application error follows this envelope:
```json
{ "error": { "code": "upstream_error", "message": "...", "details": { } } }
```

---

## Canonical variables

| `variable` | Unit | Description | Sources that emit it |
|---|---|---|---|
| `t2m_mean` | `degC` | Daily mean air temperature at 2 m | POWER, Open-Meteo, NEX-GDDP |
| `t2m_max` | `degC` | Daily max air temperature at 2 m | POWER, Open-Meteo, NEX-GDDP |
| `t2m_min` | `degC` | Daily min air temperature at 2 m | POWER, Open-Meteo, NEX-GDDP |
| `precipitation` | `mm/day` | Daily precipitation (bias-corrected when available) | POWER, Open-Meteo, IMERG, NEX-GDDP |
| `rh2m` | `%` | Daily mean relative humidity at 2 m | POWER |
| `solar_radiation` | `MJ/m^2/day` | All-sky surface shortwave downward irradiance | POWER, Open-Meteo |
| `wind2m` | `m/s` | Daily mean wind speed at 2 m | POWER, Open-Meteo |
| `ndvi` | `index` | NDVI (-1..1) | AppEEARS MODIS/VIIRS |
| `evi` | `index` | EVI | AppEEARS MODIS |
| `soil_moisture` | `m^3/m^3` | Volumetric soil moisture | AppEEARS SMAP |

---

## Health

### `GET /health`
Liveness check. Does **not** verify upstream sources.

**Response `200`**
```json
{ "status": "ok" }
```

### `GET /health/sources`
Probes every upstream in parallel. Returns status and latency.

**Response `200` — `SourcesHealth`**
```json
{
  "sources": [
    { "name": "power",       "status": "ok", "latency_ms": 212.4, "message": null },
    { "name": "open_meteo",  "status": "ok", "latency_ms":  98.1, "message": null },
    { "name": "appeears",    "status": "not_configured", "latency_ms": null, "message": "EARTHDATA_USERNAME/PASSWORD unset" },
    { "name": "earthdata",   "status": "ok", "latency_ms": 341.7, "message": null },
    { "name": "nex_gddp",    "status": "ok", "latency_ms": 180.0, "message": null },
    { "name": "copernicus",  "status": "ok", "latency_ms": 253.2, "message": null }
  ]
}
```

`status` can be: `ok`, `error`, `not_configured`, `skipped`.

---

## Climate

### `GET /api/v1/climate/history`
Daily historical series from **NASA POWER** (community = `ag`).

**Query params**
| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `lat` | `float` | yes | — | `-90..90` |
| `lon` | `float` | yes | — | `-180..180` |
| `start` | `date` | yes | — | inclusive |
| `end` | `date` | yes | — | inclusive, `>= start` |
| `format` | `json\|csv\|parquet` | no | `json` | |
| `variables` | `CanonicalVariable[]` | no | full bundle | repeatable: `?variables=t2m_mean&variables=precipitation` |

Default bundle: `t2m_mean, t2m_max, t2m_min, precipitation, rh2m, solar_radiation, wind2m`.

**Response `200` — `TimeSeries[]`** (one element per requested variable)

Per-series `metadata`:
```json
{
  "source_variable": "T2M",
  "source_unit": "degC",
  "community": "ag",
  "api": "nasa_power",
  "header_title": "..."
}
```

### `GET /api/v1/climate/forecast`
1-16 day daily forecast from **Open-Meteo** (no auth).

**Query params**
| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `lat` | `float` | yes | — | |
| `lon` | `float` | yes | — | |
| `start` | `date` | no | — | if given, `end` is also required |
| `end` | `date` | no | — | |
| `forecast_days` | `int` | no | `7` | `1..16`; ignored when `start`/`end` are given |
| `variables` | `CanonicalVariable[]` | no | bundle | |
| `format` | `json\|csv\|parquet` | no | `json` | |

Default bundle: `t2m_mean, t2m_max, t2m_min, precipitation, solar_radiation, wind2m`.

**Response `200` — `TimeSeries[]`**

Per-series `metadata`:
```json
{
  "source_variable": "temperature_2m_mean",
  "source_unit": "°C",
  "api": "open_meteo",
  "timezone": "UTC",
  "model_elevation": 123.0
}
```

---

## Precipitation

### `GET /api/v1/precipitation`
Daily precipitation from **GPM IMERG** (`GPM_3IMERGDF`) via `earthaccess`.
Requires Earthdata credentials; without them responds `503 not_configured`.

**Query params** — same as `common_query`: `lat`, `lon`, `start`, `end`, `format`.

**Response `200` — `TimeSeries`** (a single object, not a list)

- `source = "earthdata"`, `variable = "precipitation"`, `unit = "mm/day"`.
- `metadata`:
  ```json
  {
    "short_name": "GPM_3IMERGDF",
    "variable": "precipitation",
    "api": "earthaccess"
  }
  ```

---

## Vegetation

### `POST /api/v1/vegetation/jobs`
Fires an async **AppEEARS** job to extract MODIS NDVI and EVI
(`MOD13Q1.061`) at a point. Returns the `job_id` immediately; retrieve the
result via `GET /api/v1/jobs/{job_id}`.

Requires Earthdata credentials.

**Query params**
| Name | Type | Required |
|---|---|---|
| `lat` | `float` | yes |
| `lon` | `float` | yes |
| `start` | `date` | yes |
| `end` | `date` | yes |

**Response `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_modis", "status": "queued" }
```

Layers requested from the upstream:
- `MOD13Q1.061 / _250m_16_days_NDVI` → `ndvi`
- `MOD13Q1.061 / _250m_16_days_EVI` → `evi`

---

## Soil moisture

### `POST /api/v1/soil-moisture/jobs`
Async **AppEEARS** job for volumetric soil moisture from **SMAP**
(`SPL3SMP_E.006`).

Requires Earthdata credentials.

**Query params**: `lat`, `lon`, `start`, `end` (same as vegetation).

**Response `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_smap", "status": "queued" }
```

Requested layer: `SPL3SMP_E.006 / Soil_Moisture_Retrieval_Data_AM_soil_moisture`
→ `soil_moisture`.

---

## Jobs

### `GET /api/v1/jobs/{job_id}`
Fetch an AppEEARS job's status. When status is `done`, downloads the bundle
CSV and parses it into `TimeSeries`.

**Response `200` — `JobResult`**

While not yet `done`:
```json
{
  "id": "abc123",
  "status": {
    "id": "abc123",
    "source": "appeears_modis",
    "status": "running",
    "progress": null,
    "created_at": "2026-10-22T10:00:00",
    "updated_at": "2026-10-22T10:05:00",
    "message": "processing"
  },
  "series": [],
  "raw": null
}
```

Once finished, `series` carries one `TimeSeries` per layer; for NDVI/EVI the
per-series `metadata` is:
```json
{
  "product": "MOD13Q1.061",
  "layer": "_250m_16_days_NDVI",
  "api": "appeears"
}
```

**Response `404`** if the `job_id` is not in the local registry.

Upstream status → `JobStatus.status` mapping:

| AppEEARS | API |
|---|---|
| `pending` | `pending` |
| `queued` | `queued` |
| `processing`, `running` | `running` |
| `done`, `complete` | `done` |
| `expired`, `error`, `failed` | `failed` |
| anything else | `running` |

---

## Climate projections

### `GET /api/v1/projections`
Daily series from **NEX-GDDP-CMIP6** (public S3 bucket). No credentials.

**Query params**
| Name | Type | Required | Default |
|---|---|---|---|
| `lat` | `float` | yes | — |
| `lon` | `float` | yes | — |
| `start` | `date` | yes | — |
| `end` | `date` | yes | — |
| `scenario` | `string` | no | `ssp245` |
| `model` | `string` | no | `ACCESS-CM2` |
| `variables` | `CanonicalVariable[]` | no | `t2m_mean, t2m_max, t2m_min, precipitation` |
| `format` | `json\|csv\|parquet` | no | `json` |

`scenario` accepts: `historical`, `ssp126`, `ssp245`, `ssp370`, `ssp585`.

Conversions applied on serve:
- `pr` (kg m⁻² s⁻¹) → `mm/day` (× 86400)
- `tas`, `tasmax`, `tasmin` (K) → `degC` (− 273.15)

**Response `200` — `TimeSeries[]`**

Per-series `metadata`:
```json
{
  "model": "ACCESS-CM2",
  "scenario": "ssp245",
  "ensemble": "r1i1p1f1",
  "grid": "gn",
  "source_variable": "pr",
  "api": "nex_gddp_cmip6"
}
```

---

## Sentinel-2

### `GET /api/v1/sentinel-2/scenes`
STAC search for Sentinel-2 scenes on **Copernicus Data Space** that intersect
a small bbox (± 0.01°) around the point. **Does not** download assets.

**Query params**
| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `lat` | `float` | yes | — | |
| `lon` | `float` | yes | — | |
| `start` | `date` | yes | — | |
| `end` | `date` | yes | — | |
| `max_cloud_cover` | `float \| null` | no | `50.0` | `0..100`, percent; `null` disables the filter |
| `limit` | `int` | no | `20` | `1..200` |

**Response `200` — `list[object]`** (one per scene)

Each object has **only** these fields (the raw STAC feature is simplified):
| Field | Type | Notes |
|---|---|---|
| `id` | `string` | STAC item id |
| `datetime` | `string` | scene timestamp |
| `cloud_cover` | `float \| null` | `eo:cloud_cover` |
| `platform` | `string \| null` | `Sentinel-2A`, etc. |
| `collection` | `string \| null` | `SENTINEL-2` |
| `assets` | `string[]` | available asset keys |
| `self_href` | `string \| null` | `rel=self` link of the STAC item |

---

## Features (multi-source table)

### `GET /api/v1/features`
Merges POWER (mandatory) with Open-Meteo (optional) and IMERG (optional) into
a wide table, one day per row, ready for ML.

**Query params**
| Name | Type | Required | Default |
|---|---|---|---|
| `lat` | `float` | yes | — |
| `lon` | `float` | yes | — |
| `start` | `date` | yes | — |
| `end` | `date` | yes | — |
| `variables` | `CanonicalVariable[]` | no | POWER bundle |
| `include_forecast` | `bool` | no | `false` |
| `include_imerg` | `bool` | no | `false` |
| `format` | `json\|csv\|parquet` | no | `json` |

Resulting columns (example with `include_forecast=true&include_imerg=true`):

| Column | Source | Unit |
|---|---|---|
| `date` | — | `YYYY-MM-DD` |
| `t2m_mean` | POWER | `degC` |
| `t2m_max` | POWER | `degC` |
| `t2m_min` | POWER | `degC` |
| `precipitation` | POWER | `mm/day` |
| `rh2m` | POWER | `%` |
| `solar_radiation` | POWER | `MJ/m^2/day` |
| `wind2m` | POWER | `m/s` |
| `t2m_mean_forecast` | Open-Meteo | `degC` |
| `t2m_max_forecast` | Open-Meteo | `degC` |
| `t2m_min_forecast` | Open-Meteo | `degC` |
| `precipitation_forecast` | Open-Meteo | `mm/day` |
| `solar_radiation_forecast` | Open-Meteo | `MJ/m^2/day` |
| `wind2m_forecast` | Open-Meteo | `m/s` |
| `precipitation_imerg` | GPM IMERG | `mm/day` |

Notes:
- Forecast columns are omitted when `include_forecast=false`.
- `precipitation_imerg` is omitted when `include_imerg=false` **or** when
  Earthdata credentials are missing.
- NDVI/EVI and soil moisture **are not** served here: they go through the
  AppEEARS async flow (`/vegetation/jobs`, `/soil-moisture/jobs`).

**Response `200`**
- `format=json` → `list[object]`, one object per row.
- `format=csv` → `text/csv`.
- `format=parquet` → `application/octet-stream` (Parquet).
