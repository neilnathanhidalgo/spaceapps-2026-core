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
  - `GET /api/v1/climate/reanalysis`
- [Precipitation](#precipitation)
  - `GET /api/v1/precipitation`
- [Vegetation (async)](#vegetation)
  - `POST /api/v1/vegetation/jobs`
- [Soil moisture (async)](#soil-moisture)
  - `POST /api/v1/soil-moisture/jobs`
- [Water stress (async)](#water-stress)
  - `POST /api/v1/water-stress/jobs`
- [Terrain (async)](#terrain)
  - `POST /api/v1/terrain/jobs`
- [Jobs](#jobs)
  - `GET /api/v1/jobs/{job_id}`
- [Climate projections](#climate-projections)
  - `GET /api/v1/projections`
- [Crop suitability](#crop-suitability)
  - `GET /api/v1/crop-suitability`
- [Features (multi-source table)](#features-multi-source-table)
  - `GET /api/v1/features`
- [Mobile app](#mobile-app)
  - `GET /api/v1/app/climate-overview`

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
| `rh2m` | `%` | Daily mean relative humidity at 2 m | POWER, Open-Meteo, ERA5 |
| `solar_radiation` | `MJ/m^2/day` | All-sky surface shortwave downward irradiance | POWER, Open-Meteo |
| `wind2m` | `m/s` | Daily mean wind speed at 2 m | POWER, Open-Meteo |
| `ndvi` | `index` | NDVI (-1..1) | AppEEARS MODIS, HLS (Landsat + Sentinel-2) |
| `evi` | `index` | EVI | AppEEARS MODIS |
| `soil_moisture` | `m^3/m^3` | Volumetric soil moisture | AppEEARS SMAP |
| `soil_wetness` | `fraction` | Surface soil wetness (0 dry, 1 saturated), MERRA-2 | POWER (`GWETTOP`) |
| `precipitation_probability` | `%` | Daily maximum probability of precipitation | Open-Meteo |
| `weather_code` | `wmo_code` | WMO weather code of the day | Open-Meteo |
| `evaporative_stress_index` | `fraction` | Evaporative Stress Index (0 severe stress, 1 no stress) | AppEEARS ECOSTRESS |
| `elevation` | `m` | Terrain elevation above sea level | AppEEARS SRTM |

Variables served by Open-Meteo can also be requested from ERA5
(`/climate/reanalysis`), except `precipitation_probability` and `weather_code`.

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
    { "name": "era5",        "status": "ok", "latency_ms": 120.5, "message": null },
    { "name": "fao_gaez",    "status": "ok", "latency_ms": 870.3, "message": null }
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

### `GET /api/v1/climate/reanalysis`
Daily **ECMWF ERA5** reanalysis served by Open-Meteo's historical API
(`models=era5`, ~0.25°). Covers 1940 to ~5 days ago, handy to compare the
current season with El Niño years. No credentials required.

**Query params**: `lat`, `lon`, `start`, `end`, `format` and `variables`
(default `t2m_mean, t2m_max, t2m_min, precipitation, solar_radiation, wind2m, rh2m`).

**Response `200` — `list[TimeSeries]`**, with `source = "era5"` and
`metadata.api = "open_meteo_archive"`.

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
Fires an async **AppEEARS** job to extract vegetation indices at a point,
from MODIS or from HLS (Landsat + Sentinel-2). Returns the `job_id` immediately; retrieve the
result via `GET /api/v1/jobs/{job_id}`.

Requires Earthdata credentials.

**Query params**
| Name | Type | Required |
|---|---|---|
| `lat` | `float` | yes |
| `lon` | `float` | yes |
| `start` | `date` | yes |
| `end` | `date` | yes |
| `sensor` | `modis\|hls` | no (default `modis`) |

**Response `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_modis", "status": "queued" }
```

Layers requested from the upstream, by `sensor`:

| `sensor` | `source` | Layers | Resolution |
|---|---|---|---|
| `modis` | `appeears_modis` | `MOD13Q1.061 / _250m_16_days_NDVI` → `ndvi`, `MOD13Q1.061 / _250m_16_days_EVI` → `evi` | 250 m, 16-day composites since 2000 |
| `hls` | `appeears_hls` | `HLSL30_VI.020 / NDVI` (Landsat) and `HLSS30_VI.020 / NDVI` (Sentinel-2) → `ndvi` | 30 m, every 2-3 days since 2013 |

With `hls` the result holds two `ndvi` series; tell them apart by `metadata.product`.

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

## Water stress

### `POST /api/v1/water-stress/jobs`
Async **AppEEARS** job for the **ECOSTRESS** Evaporative Stress Index
(`ECO_L4T_ESI.002`, 70 m). It tells how short of water the crop is:
`0` = severe stress, `1` = no stress. Data since 2018-07-10, with irregular
overpasses (ISS orbit).

Requires Earthdata credentials.

**Query params**: `lat`, `lon`, `start`, `end`.

**Response `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_ecostress", "status": "queued" }
```

Requested layer: `ECO_L4T_ESI.002 / ESI` → `evaporative_stress_index`.

---

## Terrain

### `POST /api/v1/terrain/jobs`
Async **AppEEARS** job for **SRTM** elevation (`SRTMGL1_NC.003`, 30 m). It is
static data: dates are pinned to the SRTM mission (2000-02-11 to 2000-02-21),
so it only takes `lat` and `lon`.

Requires Earthdata credentials.

**Response `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_srtm", "status": "queued" }
```

Requested layer: `SRTMGL1_NC.003 / SRTMGL1_DEM` → `elevation`.

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

Once finished, `series` carries one `TimeSeries` per layer (AppEEARS writes one
CSV per product and all of them are merged); for NDVI/EVI the
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

## Crop suitability

### `GET /api/v1/crop-suitability`
**FAO GAEZ v4** rainfed crop suitability index for the 1981-2010 baseline
climate, on ~9 km cells. No credentials required.

> In irrigated coastal valleys (e.g. coastal Piura) rainfed suitability is `0`
> for almost every crop: the index reflects what rainfall allows, not irrigation.
>
> FAO's server takes ~2-4 s per crop. The first request for a cell with the 20
> default crops can take several minutes; afterwards it is served from cache
> (`CACHE_TTL_STATIC`, 30 days).

**Query params**
| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `lat` | `float` | yes | — | |
| `lon` | `float` | yes | — | |
| `input_level` | `high\|low` | no | `high` | `high`: mechanized farming; `low`: traditional |
| `crops` | `string[]` | no | 20 crops of the pilot region | GAEZ names (`Maize`, `Wetland rice`, `White potato`…); case-insensitive |

An unknown crop returns `400 invalid_request` with the available names in
`error.details.available`.

**Response `200` — `CropSuitabilityReport`**
```json
{
  "location": { "lat": -5.24, "lon": -79.45, "geometry": null },
  "period": "1981-2010",
  "water_supply": "rainfed",
  "input_level": "high",
  "crops": [
    { "crop": "Phaseolus bean", "suitability_index": 0.2788 },
    { "crop": "Maize", "suitability_index": 0.1917 },
    { "crop": "Cotton", "suitability_index": 0.0 }
  ],
  "source": "fao_gaez",
  "retrieved_at": "2026-11-14T12:00:00"
}
```

`crops` is sorted from most to least suitable; `suitability_index` is `null`
when GAEZ has no data for the cell.

---

## Features (multi-source table)

### `GET /api/v1/features`
Merges POWER (mandatory) with Open-Meteo, ERA5 and IMERG (optional) into
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
| `include_era5` | `bool` | no | `false` |
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
- With `include_era5=true` the same variables are added with an `_era5` suffix
  (e.g. `precipitation_era5`); those ERA5 lacks (such as `soil_wetness`) are skipped.
- `precipitation_imerg` is omitted when `include_imerg=false` **or** when
  Earthdata credentials are missing.
- NDVI/EVI and soil moisture **are not** served here: they go through the
  AppEEARS async flow (`/vegetation/jobs`, `/soil-moisture/jobs`).

**Response `200`**
- `format=json` → `list[object]`, one object per row.
- `format=csv` → `text/csv`.
- `format=parquet` → `application/octet-stream` (Parquet).

---

## Mobile app

### `GET /api/v1/app/climate-overview`
Ready-to-render summary for the **Clima** screen of the app (Siembra Segura).
No credentials needed.

- 7-day **Open-Meteo** forecast in the point's local time zone.
- Comparison with a normal year: last 30 valid days of **NASA POWER** daily
  data against the **NASA POWER** monthly climatology for the same dates:
  rainfall (`PRECTOTCORR`), mean temperature (`T2M`) and soil wetness
  (`GWETTOP`).
- If POWER fails, the response is still `200` with `anomalies: []`.

**Query params**: `lat`, `lon` (required).

**Response `200` — `ClimateOverview`**: see the Spanish reference
(`API.md`) for a full example.

| Field | Values |
|---|---|
| `condition` | `sunny`, `cloudy`, `rain` (≥ 1 mm), `moderate_rain` (≥ 10 mm), `heavy_rain` (≥ 30 mm) |
| `metric` | `rainfall`, `temperature`, `soil_moisture` |
| `comparison.type` | `times_normal` (`factor` > 0, clamped to 0.1–10), `degrees_from_normal` (`delta` in °C), `moisture_category` (`level`: `dry`, `normal`, `wet`, `very_wet`; ±0.1 and +0.2 thresholds on `GWETTOP`) |
| `observed_level`, `normal_level` | Bar position (0..1) |
| `advice` | Spanish text starting in lowercase; the app prefixes it with "Qué hacer:" |
