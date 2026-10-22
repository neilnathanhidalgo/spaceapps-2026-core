# Referencia de la API

Documento de referencia de todos los endpoints expuestos por `spaceapps-2026-core`.
Generado a partir del código en `src/spaceapps_core/`.

- Prefijo base: `/api/v1` (los endpoints de salud viven en la raíz).
- Todos los endpoints de datos aceptan `format=json|csv|parquet` cuando devuelven
  series temporales. `csv` → `text/csv`, `parquet` → `application/octet-stream`.
- Las fechas van en formato ISO (`YYYY-MM-DD`).
- Las coordenadas se validan: `lat ∈ [-90, 90]`, `lon ∈ [-180, 180]`.

## Índice

- [Esquemas comunes](#esquemas-comunes)
- [Variables canónicas](#variables-canónicas)
- [Salud](#salud)
  - `GET /health`
  - `GET /health/sources`
- [Clima](#clima)
  - `GET /api/v1/climate/history`
  - `GET /api/v1/climate/forecast`
- [Precipitación](#precipitación)
  - `GET /api/v1/precipitation`
- [Vegetación (asíncrono)](#vegetación)
  - `POST /api/v1/vegetation/jobs`
- [Humedad de suelo (asíncrono)](#humedad-de-suelo)
  - `POST /api/v1/soil-moisture/jobs`
- [Jobs](#jobs)
  - `GET /api/v1/jobs/{job_id}`
- [Proyecciones climáticas](#proyecciones-climáticas)
  - `GET /api/v1/projections`
- [Sentinel-2](#sentinel-2)
  - `GET /api/v1/sentinel-2/scenes`
- [Features (tabla multi-fuente)](#features-tabla-multi-fuente)
  - `GET /api/v1/features`

---

## Esquemas comunes

### `Location`
| Campo | Tipo | Notas |
|---|---|---|
| `lat` | `float` | `-90..90` |
| `lon` | `float` | `-180..180` |
| `geometry` | `object \| null` | GeoJSON opcional (Polygon/MultiPolygon) |

### `TimePoint`
| Campo | Tipo | Notas |
|---|---|---|
| `date` | `date` (`YYYY-MM-DD`) | |
| `value` | `float \| null` | `null` = dato faltante/NaN |

### `TimeSeries`
Es la forma unificada de **todos** los clientes de datos.

| Campo | Tipo | Notas |
|---|---|---|
| `source` | `string` | `power`, `open_meteo`, `appeears`, `earthdata`, `nex_gddp` |
| `variable` | `CanonicalVariable` | ver tabla de abajo |
| `unit` | `string` | p.ej. `degC`, `mm/day`, `%`, `m/s`, `index`, `m^3/m^3`, `MJ/m^2/day` |
| `location` | `Location` | |
| `temporal_resolution` | `"daily" \| "hourly" \| "monthly" \| "climatology"` | hoy casi siempre `daily` |
| `points` | `TimePoint[]` | ordenados por fecha |
| `metadata` | `object` | específico por fuente (ver cada endpoint) |
| `retrieved_at` | `datetime` (UTC) | timestamp de la respuesta |

### `JobStatus`
| Campo | Tipo | Notas |
|---|---|---|
| `id` | `string` | task id de AppEEARS |
| `source` | `string` | `appeears_modis` o `appeears_smap` |
| `status` | `"pending" \| "queued" \| "running" \| "done" \| "failed"` | mapeado desde AppEEARS |
| `progress` | `float \| null` | `0..1` |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | |
| `message` | `string \| null` | estado crudo del upstream |

### `JobResult`
| Campo | Tipo | Notas |
|---|---|---|
| `id` | `string` | |
| `status` | `JobStatus` | |
| `series` | `TimeSeries[]` | vacío mientras no esté `done` |
| `raw` | `object \| null` | reservado para debugging |

### `ErrorResponse`
Todos los errores de aplicación siguen este envelope:
```json
{ "error": { "code": "upstream_error", "message": "...", "details": { } } }
```

---

## Variables canónicas

| `variable` | Unidad | Descripción | Fuentes que la emiten |
|---|---|---|---|
| `t2m_mean` | `degC` | Temperatura media diaria a 2 m | POWER, Open-Meteo, NEX-GDDP |
| `t2m_max` | `degC` | Temperatura máxima diaria a 2 m | POWER, Open-Meteo, NEX-GDDP |
| `t2m_min` | `degC` | Temperatura mínima diaria a 2 m | POWER, Open-Meteo, NEX-GDDP |
| `precipitation` | `mm/day` | Precipitación diaria (bias-corrected si aplica) | POWER, Open-Meteo, IMERG, NEX-GDDP |
| `rh2m` | `%` | Humedad relativa media a 2 m | POWER |
| `solar_radiation` | `MJ/m^2/day` | Irradiancia SW en superficie, cielo total | POWER, Open-Meteo |
| `wind2m` | `m/s` | Velocidad del viento a 2 m | POWER, Open-Meteo |
| `ndvi` | `index` | NDVI (-1..1) | AppEEARS MODIS/VIIRS |
| `evi` | `index` | EVI | AppEEARS MODIS |
| `soil_moisture` | `m^3/m^3` | Humedad del suelo volumétrica | AppEEARS SMAP |

---

## Salud

### `GET /health`
Chequeo de liveness. **No** verifica fuentes.

**Respuesta `200`**
```json
{ "status": "ok" }
```

### `GET /health/sources`
Prueba cada fuente aguas arriba en paralelo. Devuelve estado y latencia.

**Respuesta `200` — `SourcesHealth`**
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

`status` puede ser: `ok`, `error`, `not_configured`, `skipped`.

---

## Clima

### `GET /api/v1/climate/history`
Serie diaria histórica desde **NASA POWER** (community = `ag`).

**Query params**
| Nombre | Tipo | Requerido | Default | Notas |
|---|---|---|---|---|
| `lat` | `float` | sí | — | `-90..90` |
| `lon` | `float` | sí | — | `-180..180` |
| `start` | `date` | sí | — | inclusive |
| `end` | `date` | sí | — | inclusive, `>= start` |
| `format` | `json\|csv\|parquet` | no | `json` | |
| `variables` | `CanonicalVariable[]` | no | bundle completo | repetible: `?variables=t2m_mean&variables=precipitation` |

Bundle por defecto: `t2m_mean, t2m_max, t2m_min, precipitation, rh2m, solar_radiation, wind2m`.

**Respuesta `200` — `TimeSeries[]`** (un elemento por variable solicitada)

`metadata` por serie:
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
Pronóstico diario 1-16 días desde **Open-Meteo** (sin autenticación).

**Query params**
| Nombre | Tipo | Requerido | Default | Notas |
|---|---|---|---|---|
| `lat` | `float` | sí | — | |
| `lon` | `float` | sí | — | |
| `start` | `date` | no | — | si se da, también `end` |
| `end` | `date` | no | — | |
| `forecast_days` | `int` | no | `7` | `1..16`; se ignora si hay `start`/`end` |
| `variables` | `CanonicalVariable[]` | no | bundle | |
| `format` | `json\|csv\|parquet` | no | `json` | |

Bundle por defecto: `t2m_mean, t2m_max, t2m_min, precipitation, solar_radiation, wind2m`.

**Respuesta `200` — `TimeSeries[]`**

`metadata` por serie:
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

## Precipitación

### `GET /api/v1/precipitation`
Precipitación diaria de **GPM IMERG** (`GPM_3IMERGDF`) vía `earthaccess`.
Requiere credenciales Earthdata; si faltan responde `503 not_configured`.

**Query params** — iguales a `common_query`: `lat`, `lon`, `start`, `end`, `format`.

**Respuesta `200` — `TimeSeries`** (un único objeto, no una lista)

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

## Vegetación

### `POST /api/v1/vegetation/jobs`
Dispara un job asíncrono en **AppEEARS** para extraer NDVI y EVI de MODIS
(`MOD13Q1.061`) sobre un punto. Devuelve inmediatamente el `job_id`; consulta
el resultado en `GET /api/v1/jobs/{job_id}`.

Requiere credenciales Earthdata.

**Query params**
| Nombre | Tipo | Requerido |
|---|---|---|
| `lat` | `float` | sí |
| `lon` | `float` | sí |
| `start` | `date` | sí |
| `end` | `date` | sí |

**Respuesta `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_modis", "status": "queued" }
```

Layers que se solicitan al upstream:
- `MOD13Q1.061 / _250m_16_days_NDVI` → `ndvi`
- `MOD13Q1.061 / _250m_16_days_EVI` → `evi`

---

## Humedad de suelo

### `POST /api/v1/soil-moisture/jobs`
Job asíncrono en **AppEEARS** para humedad de suelo volumétrica de **SMAP**
(`SPL3SMP_E.006`).

Requiere credenciales Earthdata.

**Query params**: `lat`, `lon`, `start`, `end` (iguales a vegetación).

**Respuesta `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_smap", "status": "queued" }
```

Layer solicitado: `SPL3SMP_E.006 / Soil_Moisture_Retrieval_Data_AM_soil_moisture`
→ `soil_moisture`.

---

## Jobs

### `GET /api/v1/jobs/{job_id}`
Consulta el estado de un job AppEEARS. Cuando el estado es `done`, descarga el
CSV del bundle y lo parsea a `TimeSeries`.

**Respuesta `200` — `JobResult`**

Mientras no esté `done`:
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

Al terminar, `series` trae un `TimeSeries` por layer; para NDVI/EVI el
`metadata` por serie es:
```json
{
  "product": "MOD13Q1.061",
  "layer": "_250m_16_days_NDVI",
  "api": "appeears"
}
```

**Respuesta `404`** si el `job_id` no está en el registro local.

Mapeo de estado upstream → `JobStatus.status`:

| AppEEARS | API |
|---|---|
| `pending` | `pending` |
| `queued` | `queued` |
| `processing`, `running` | `running` |
| `done`, `complete` | `done` |
| `expired`, `error`, `failed` | `failed` |
| cualquier otro | `running` |

---

## Proyecciones climáticas

### `GET /api/v1/projections`
Series diarias de **NEX-GDDP-CMIP6** (bucket público en S3). Sin credenciales.

**Query params**
| Nombre | Tipo | Requerido | Default |
|---|---|---|---|
| `lat` | `float` | sí | — |
| `lon` | `float` | sí | — |
| `start` | `date` | sí | — |
| `end` | `date` | sí | — |
| `scenario` | `string` | no | `ssp245` |
| `model` | `string` | no | `ACCESS-CM2` |
| `variables` | `CanonicalVariable[]` | no | `t2m_mean, t2m_max, t2m_min, precipitation` |
| `format` | `json\|csv\|parquet` | no | `json` |

`scenario` admite: `historical`, `ssp126`, `ssp245`, `ssp370`, `ssp585`.

Conversiones aplicadas al servir:
- `pr` (kg m⁻² s⁻¹) → `mm/day` (× 86400)
- `tas`, `tasmax`, `tasmin` (K) → `degC` (− 273.15)

**Respuesta `200` — `TimeSeries[]`**

`metadata` por serie:
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
Búsqueda STAC de escenas Sentinel-2 en **Copernicus Data Space** que intersectan
un pequeño bbox (± 0.01°) alrededor del punto. **No** descarga assets.

**Query params**
| Nombre | Tipo | Requerido | Default | Notas |
|---|---|---|---|---|
| `lat` | `float` | sí | — | |
| `lon` | `float` | sí | — | |
| `start` | `date` | sí | — | |
| `end` | `date` | sí | — | |
| `max_cloud_cover` | `float \| null` | no | `50.0` | `0..100`, en %; `null` para desactivar el filtro |
| `limit` | `int` | no | `20` | `1..200` |

**Respuesta `200` — `list[object]`** (una por escena)

Cada objeto tiene **sólo** estos campos (el STAC crudo se simplifica):
| Campo | Tipo | Notas |
|---|---|---|
| `id` | `string` | id del item STAC |
| `datetime` | `string` | timestamp de la escena |
| `cloud_cover` | `float \| null` | `eo:cloud_cover` |
| `platform` | `string \| null` | `Sentinel-2A`, etc. |
| `collection` | `string \| null` | `SENTINEL-2` |
| `assets` | `string[]` | nombres de assets disponibles |
| `self_href` | `string \| null` | link `rel=self` del STAC item |

---

## Features (tabla multi-fuente)

### `GET /api/v1/features`
Mezcla POWER (obligatorio) con Open-Meteo (opcional) e IMERG (opcional) en una
tabla ancha, un día por fila, lista para ML.

**Query params**
| Nombre | Tipo | Requerido | Default |
|---|---|---|---|
| `lat` | `float` | sí | — |
| `lon` | `float` | sí | — |
| `start` | `date` | sí | — |
| `end` | `date` | sí | — |
| `variables` | `CanonicalVariable[]` | no | bundle POWER |
| `include_forecast` | `bool` | no | `false` |
| `include_imerg` | `bool` | no | `false` |
| `format` | `json\|csv\|parquet` | no | `json` |

Columnas resultantes (ejemplo con `include_forecast=true&include_imerg=true`):

| Columna | Fuente | Unidad |
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

Notas:
- Las columnas de forecast se omiten si `include_forecast=false`.
- `precipitation_imerg` se omite si `include_imerg=false` **o** si no hay
  credenciales Earthdata.
- Las variables NDVI/EVI y humedad de suelo **no** entran aquí: viven en el
  flujo asíncrono de AppEEARS (`/vegetation/jobs`, `/soil-moisture/jobs`).

**Respuesta `200`**
- `format=json` → `list[object]`, un objeto por fila.
- `format=csv` → `text/csv`.
- `format=parquet` → `application/octet-stream` (Parquet).
