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
  - `GET /api/v1/climate/reanalysis`
- [Precipitación](#precipitación)
  - `GET /api/v1/precipitation`
- [Vegetación (asíncrono)](#vegetación)
  - `POST /api/v1/vegetation/jobs`
- [Humedad de suelo (asíncrono)](#humedad-de-suelo)
  - `POST /api/v1/soil-moisture/jobs`
- [Estrés hídrico (asíncrono)](#estrés-hídrico)
  - `POST /api/v1/water-stress/jobs`
- [Terreno (asíncrono)](#terreno)
  - `POST /api/v1/terrain/jobs`
- [Jobs](#jobs)
  - `GET /api/v1/jobs/{job_id}`
- [Proyecciones climáticas](#proyecciones-climáticas)
  - `GET /api/v1/projections`
- [Aptitud de cultivos](#aptitud-de-cultivos)
  - `GET /api/v1/crop-suitability`
- [Features (tabla multi-fuente)](#features-tabla-multi-fuente)
  - `GET /api/v1/features`
- [App móvil](#app-móvil)
  - `GET /api/v1/app/climate-overview`
  - `GET /api/v1/app/catalog`
  - `POST /api/v1/app/recommendation`

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
| `rh2m` | `%` | Humedad relativa media a 2 m | POWER, Open-Meteo, ERA5 |
| `solar_radiation` | `MJ/m^2/day` | Irradiancia SW en superficie, cielo total | POWER, Open-Meteo |
| `wind2m` | `m/s` | Velocidad del viento a 2 m | POWER, Open-Meteo |
| `ndvi` | `index` | NDVI (-1..1) | AppEEARS MODIS, HLS (Landsat + Sentinel-2) |
| `evi` | `index` | EVI | AppEEARS MODIS |
| `soil_moisture` | `m^3/m^3` | Humedad del suelo volumétrica | AppEEARS SMAP |
| `soil_wetness` | `fraction` | Humedad superficial del suelo (0 seco, 1 saturado), MERRA-2 | POWER (`GWETTOP`) |
| `precipitation_probability` | `%` | Probabilidad máxima diaria de lluvia | Open-Meteo |
| `weather_code` | `wmo_code` | Código WMO del tiempo del día | Open-Meteo |
| `evaporative_stress_index` | `fraction` | Índice de estrés evaporativo (0 estrés severo, 1 sin estrés) | AppEEARS ECOSTRESS |
| `elevation` | `m` | Elevación del terreno sobre el nivel del mar | AppEEARS SRTM |

Las variables con fuente Open-Meteo también se pueden pedir a ERA5
(`/climate/reanalysis`), salvo `precipitation_probability` y `weather_code`.

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
    { "name": "era5",        "status": "ok", "latency_ms": 120.5, "message": null },
    { "name": "fao_gaez",    "status": "ok", "latency_ms": 870.3, "message": null }
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

### `GET /api/v1/climate/reanalysis`
Reanálisis diario **ECMWF ERA5** servido por la API histórica de Open-Meteo
(`models=era5`, ~0.25°). Cubre desde 1940 hasta hace ~5 días, útil para comparar
la campaña actual con años de El Niño. No requiere credenciales.

**Query params**: `lat`, `lon`, `start`, `end`, `format` y `variables`
(por defecto `t2m_mean, t2m_max, t2m_min, precipitation, solar_radiation, wind2m, rh2m`).

**Respuesta `200` — `list[TimeSeries]`**, con `source = "era5"` y
`metadata.api = "open_meteo_archive"`.

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
Dispara un job asíncrono en **AppEEARS** para extraer índices de vegetación
sobre un punto, de MODIS o de HLS (Landsat + Sentinel-2). Devuelve inmediatamente el `job_id`; consulta
el resultado en `GET /api/v1/jobs/{job_id}`.

Requiere credenciales Earthdata.

**Query params**
| Nombre | Tipo | Requerido |
|---|---|---|
| `lat` | `float` | sí |
| `lon` | `float` | sí |
| `start` | `date` | sí |
| `end` | `date` | sí |
| `sensor` | `modis\|hls` | no (default `modis`) |

**Respuesta `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_modis", "status": "queued" }
```

Layers que se solicitan al upstream según `sensor`:

| `sensor` | `source` | Layers | Resolución |
|---|---|---|---|
| `modis` | `appeears_modis` | `MOD13Q1.061 / _250m_16_days_NDVI` → `ndvi`, `MOD13Q1.061 / _250m_16_days_EVI` → `evi` | 250 m, compuestos de 16 días desde 2000 |
| `hls` | `appeears_hls` | `HLSL30_VI.020 / NDVI` (Landsat) y `HLSS30_VI.020 / NDVI` (Sentinel-2) → `ndvi` | 30 m, cada 2-3 días desde 2013 |

Con `hls` el resultado trae dos series `ndvi`; se distinguen por `metadata.product`.

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

## Estrés hídrico

### `POST /api/v1/water-stress/jobs`
Job asíncrono en **AppEEARS** para el índice de estrés evaporativo de
**ECOSTRESS** (`ECO_L4T_ESI.002`, 70 m). Indica cuánto le falta de agua al
cultivo: `0` = estrés severo, `1` = sin estrés. Datos desde 2018-07-10, con
pasadas irregulares (órbita de la ISS).

Requiere credenciales Earthdata.

**Query params**: `lat`, `lon`, `start`, `end`.

**Respuesta `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_ecostress", "status": "queued" }
```

Layer solicitado: `ECO_L4T_ESI.002 / ESI` → `evaporative_stress_index`.

---

## Terreno

### `POST /api/v1/terrain/jobs`
Job asíncrono en **AppEEARS** para la elevación **SRTM** (`SRTMGL1_NC.003`, 30 m).
Es un dato estático: las fechas se fijan a la misión SRTM (2000-02-11 a
2000-02-21), así que solo recibe `lat` y `lon`.

Requiere credenciales Earthdata.

**Respuesta `200`**
```json
{ "job_id": "<task_id>", "source": "appeears_srtm", "status": "queued" }
```

Layer solicitado: `SRTMGL1_NC.003 / SRTMGL1_DEM` → `elevation`.

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

Al terminar, `series` trae un `TimeSeries` por layer (AppEEARS genera un CSV
por producto y se combinan todos); para NDVI/EVI el
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

## Aptitud de cultivos

### `GET /api/v1/crop-suitability`
Índice de aptitud de **FAO GAEZ v4** para cultivos de secano, con el clima de
referencia 1981-2010 y celdas de ~9 km. No requiere credenciales.

> En valles costeros con riego (p. ej. Piura costa) el secano da `0` para casi
> todo: el índice refleja lo que permite la lluvia, no el riego.
>
> El servidor de la FAO tarda ~2-4 s por cultivo. La primera consulta de una
> celda con los 20 cultivos por defecto puede tardar varios minutos; después se
> sirve de caché (`CACHE_TTL_STATIC`, 30 días).

**Query params**
| Nombre | Tipo | Requerido | Default | Notas |
|---|---|---|---|---|
| `lat` | `float` | sí | — | |
| `lon` | `float` | sí | — | |
| `input_level` | `high\|low` | no | `high` | `high`: agricultura tecnificada; `low`: tradicional |
| `crops` | `string[]` | no | 20 cultivos de la zona piloto | Nombres GAEZ (`Maize`, `Wetland rice`, `White potato`…); sin distinguir mayúsculas |

Un cultivo desconocido devuelve `400 invalid_request` con la lista de
disponibles en `error.details.available`.

**Respuesta `200` — `CropSuitabilityReport`**
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

`crops` viene ordenado de más a menos apto; `suitability_index` es `null` si
GAEZ no tiene dato en la celda.

---

## Features (tabla multi-fuente)

### `GET /api/v1/features`
Mezcla POWER (obligatorio) con Open-Meteo, ERA5 e IMERG (opcionales) en una
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
| `include_era5` | `bool` | no | `false` |
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
- Con `include_era5=true` se agregan las mismas variables con sufijo `_era5`
  (p. ej. `precipitation_era5`); las que ERA5 no tiene (como `soil_wetness`) se omiten.
- `precipitation_imerg` se omite si `include_imerg=false` **o** si no hay
  credenciales Earthdata.
- Las variables NDVI/EVI y humedad de suelo **no** entran aquí: viven en el
  flujo asíncrono de AppEEARS (`/vegetation/jobs`, `/soil-moisture/jobs`).

**Respuesta `200`**
- `format=json` → `list[object]`, un objeto por fila.
- `format=csv` → `text/csv`.
- `format=parquet` → `application/octet-stream` (Parquet).

---

## App móvil

### `GET /api/v1/app/climate-overview`
Resumen listo para pintar la pantalla **Clima** de la app (Siembra Segura).
No requiere credenciales.

- Pronóstico de 7 días de **Open-Meteo** en la zona horaria local del punto.
- Comparación con un año normal: últimos 30 días válidos de **NASA POWER**
  (diario) frente a la climatología mensual de **NASA POWER** para las mismas
  fechas: lluvia (`PRECTOTCORR`), temperatura media (`T2M`) y humedad del
  suelo (`GWETTOP`).
- Si POWER falla, la respuesta sigue siendo `200` con `anomalies: []`.

**Query params**: `lat`, `lon` (obligatorios).

**Respuesta `200` — `ClimateOverview`**
```json
{
  "location": { "lat": -5.19, "lon": -80.63, "geometry": null },
  "today": {
    "date": "2026-11-13", "condition": "moderate_rain",
    "rain_probability": 0.7, "rain_mm": 12.0, "temperature_c": 31.0
  },
  "week": [ { "date": "2026-11-13", "condition": "moderate_rain", "rain_mm": 12.0 } ],
  "advice": "no siembres ni abones hasta el jueves. Tu suelo ya está muy húmedo.",
  "anomalies": [
    {
      "metric": "rainfall", "observed_level": 0.9, "normal_level": 0.3,
      "comparison": { "type": "times_normal", "factor": 3.0 },
      "observed_value": 90.0, "normal_value": 30.0, "unit": "mm",
      "period_start": "2026-10-08", "period_end": "2026-11-06"
    }
  ],
  "sources": ["open_meteo", "nasa_power"],
  "generated_at": "2026-11-13T15:00:00"
}
```

| Campo | Valores |
|---|---|
| `condition` | `sunny`, `cloudy`, `rain` (≥ 1 mm), `moderate_rain` (≥ 10 mm), `heavy_rain` (≥ 30 mm) |
| `metric` | `rainfall`, `temperature`, `soil_moisture` |
| `comparison.type` | `times_normal` (`factor` > 0, acotado a 0.1–10), `degrees_from_normal` (`delta` en °C), `moisture_category` (`level`: `dry`, `normal`, `wet`, `very_wet`; umbrales de ±0.1 y +0.2 sobre `GWETTOP`) |
| `observed_level`, `normal_level` | Posición en la barra (0..1) |
| `advice` | Texto en español que empieza en minúscula; la app le antepone "Qué hacer:" |

---

### `GET /api/v1/app/catalog`
Cultivos, prioridades y restricciones entre las que elige el agricultor.
Sale del archivo de parámetros agronómicos
(`src/spaceapps_core/data/agro_config.json`, configurable con
`AGRO_CONFIG_PATH`). No requiere credenciales.

**Sin parámetros.**

**Respuesta `200` — `AppCatalog`**
```json
{
  "crops": [
    { "id": "rice", "name": "Arroz", "cycle_months": 5, "soil_impact": "degrades" },
    { "id": "maize", "name": "Maíz", "cycle_months": 4, "soil_impact": "neutral" }
  ],
  "priorities": [
    { "id": "lower-climate-risk", "name": "Menos riesgo de clima", "phrase": "tener menos riesgo de clima" },
    { "id": "save-water", "name": "Cuidar mi agua", "phrase": "cuidar tu agua" },
    { "id": "restore-soil", "name": "Recuperar mi tierra", "phrase": "recuperar tu tierra" }
  ],
  "restrictions": [
    { "id": "no-cotton-buyer", "name": "No tengo comprador para algodón" },
    { "id": "low-water", "name": "Tendré poca agua" }
  ],
  "example_parameters": true
}
```

| Campo | Notas |
|---|---|
| `priorities` | En orden de presentación; **la primera es la sugerida** cuando el agricultor no elige |
| `cycle_months` | Duración del ciclo del cultivo, en meses (= largo de `kc_by_month`) |
| `soil_impact` | `degrades`, `neutral`, `improves`, `improves_a_lot` |
| `example_parameters` | `true` mientras algún bloque del JSON siga marcado con `"_example": true` |

---

### `POST /api/v1/app/recommendation`
Recomendación de rotación para la pantalla **Qué sembrar** (y "¿Cuándo
siembro?" y "Rotación"). Calcula **los tres escenarios de una sola vez**, para
que la app pueda cambiar de escenario sin volver a pedir datos. Solo usa
**NASA POWER** (sin credenciales) y el archivo de parámetros agronómicos.

**Cómo se calcula**

1. **Clima del escenario:** para cada escenario (`heavy_rains`, `normal`,
   `dry`) se bajan los años de referencia de `scenarios` (POWER diario:
   `PRECTOTCORR`, `T2M_MAX`, `T2M_MIN`) y se promedian por mes del año: la
   lluvia como media de los acumulados mensuales, las temperaturas como media
   de los valores diarios.
2. **ET0 mensual:** Hargreaves-Samani (`services/et0.py: reference_et0`) con
   `T2M_MAX`, `T2M_MIN` y la radiación extraterrestre de la latitud a mitad de
   mes. Está aislada para poder reemplazarla por Penman-Monteith.
3. **Calendario:** el primer cultivo arranca en el **mes** de `planting_date` y
   cada cultivo siguiente empieza cuando termina el anterior; la duración de
   cada uno es el largo de su `kc_by_month`.
4. **Agua de riego:** por mes calendario,
   `max(0, ET0 × Kc × días_del_mes − lluvia_efectiva)` en mm
   (`lluvia_efectiva = lluvia_mensual × effective_rain_fraction`),
   × `area_ha` × 10 para pasar a m³. Se suma por cultivo y por rotación.
5. **Meses de riesgo:** meses del año cuya lluvia del escenario supera
   `risk_month_rain_mm`. El riesgo de una opción es cuántos meses de **su**
   calendario caen en esos meses, con nivel `low` / `medium` / `high` según
   `climate_risk_medium_months` y `climate_risk_high_months`.
6. **Tierra:** el estado actual sale del último cultivo y de cuántas campañas
   seguidas lleva con él
   (`soil_baseline_score + impacto_del_cultivo × (campañas − soil_campaigns_before_penalty)`,
   acotado a la escala `very_tired` → `good`). El estado "en dos años" aplica el
   `soil_impact` de cada cultivo de la rotación, repitiéndola hasta cubrir
   `soil_horizon_months`.
7. **Restricciones:** cada opción trae `excluded_by` con las restricciones que
   la descartan; **ninguna opción se elimina de la respuesta** (la app ya sabe
   ocultarlas). Una restricción descarta por cultivo (`excludes_crop_ids`) o por
   consumo de agua (`excludes_high_water_use`, cuando el agua por hectárea
   supera `low_water_m3_per_ha` **en algún escenario**).
8. **Ranking por prioridad y escenario** (se calcula para **todas** las
   prioridades del catálogo, no solo la elegida):
   - `save-water` (`least_water`): menos agua de riego;
   - `restore-soil` (`most_soil_improvement`): mayor mejora de la tierra; en
     empate, menos meses de riesgo;
   - `lower-climate-risk` (`least_climate_risk`): menos meses de riesgo; en
     empate, menos agua.

   Los empates conservan el orden del catálogo.

**Cuerpo — `RecommendationRequest`** (`extra="forbid"`: un campo desconocido
responde `422`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `lat` | `float` | Sí | `-90..90` |
| `lon` | `float` | Sí | `-180..180` |
| `planting_date` | `date` | Sí | Fecha que ingresa el agricultor |
| `area_ha` | `float` | No (`1.0`) | `> 0`, hectáreas de la parcela |
| `last_crop_id` | `string \| null` | No (`null`) | `null` usa `defaults.last_crop_id` |
| `consecutive_campaigns` | `int` | No (`1`) | `>= 0`, campañas seguidas con ese cultivo |
| `priority_id` | `string \| null` | No (`null`) | `null` usa la primera prioridad del catálogo |
| `restriction_ids` | `string[]` | No (`[]`) | Ids del catálogo |

```json
{
  "lat": -5.19, "lon": -80.63,
  "area_ha": 2.0,
  "planting_date": "2026-12-15",
  "last_crop_id": "rice",
  "consecutive_campaigns": 3,
  "priority_id": "save-water",
  "restriction_ids": ["low-water"]
}
```

Un `priority_id`, `restriction_id` o `last_crop_id` que no exista responde
`400 invalid_request` **sin** llamar a NASA POWER.

**Respuesta `200` — `RecommendationResponse`** (recortada: `monthly`,
`long_term_plan` y `monthly_climate` van completos)
```json
{
  "location": { "lat": -5.19, "lon": -80.63, "geometry": null },
  "area_ha": 2.0,
  "planting_date": "2026-12-15",
  "priority_id": "save-water",
  "restriction_ids": ["low-water"],
  "options": [
    {
      "id": "r1",
      "crop_ids": ["maize", "bean"],
      "cycle_months": 7,
      "soil_impact": "improves_a_lot",
      "soil_impact_score": 2,
      "soil_in_two_years": "good",
      "factsheet": {
        "rationale": "El maíz aguanta mejor el clima que el arroz. El frejol le devuelve fuerza a tu tierra.",
        "evidence": "…", "benefits": "…", "unknowns": "…", "risks": "…"
      },
      "excluded_by": [],
      "calendar": {
        "planting_date": "2026-12-15",
        "decision_deadline": "2026-12-15",
        "timeline_start": "2026-12-01",
        "timeline_months": 7,
        "periods": [
          { "crop_id": "maize", "start": "2026-12-01", "month_count": 4 },
          { "crop_id": "bean", "start": "2027-04-01", "month_count": 3 }
        ],
        "instructions": "Siembra el maíz en la primera quincena del mes."
      },
      "long_term_plan": [
        { "crop_id": "maize", "start": "2026-12-01", "end": "2027-03-01", "soil_after": "tired" },
        { "crop_id": "bean", "start": "2027-04-01", "end": "2027-06-01", "soil_after": "good" }
      ],
      "scenarios": {
        "normal": {
          "irrigation_m3": 12786.0,
          "irrigation_m3_per_ha": 6393.0,
          "risk_months": [],
          "risk_month_count": 0,
          "climate_risk": "low",
          "monthly": [
            {
              "month": "2026-12-01", "crop_id": "maize", "kc": 0.4,
              "et0_mm_day": 5.36, "rain_mm": 15.0, "effective_rain_mm": 12.0,
              "irrigation_mm": 54.5, "irrigation_m3": 1090.2
            }
          ]
        }
      }
    }
  ],
  "ranking": {
    "save-water": {
      "heavy_rains": ["r3", "r1", "r2"],
      "normal": ["r1", "r3", "r2"],
      "dry": ["r1", "r3", "r2"]
    },
    "restore-soil": { "heavy_rains": ["r2", "r1", "r3"], "normal": ["r2", "r1", "r3"], "dry": ["r2", "r1", "r3"] },
    "lower-climate-risk": { "heavy_rains": ["r3", "r1", "r2"], "normal": ["r1", "r3", "r2"], "dry": ["r1", "r3", "r2"] }
  },
  "current_practice": {
    "crop_ids": ["rice", "rice"],
    "consecutive_campaigns": 3,
    "cycle_months": 10,
    "soil_in_two_years": "very_tired",
    "factsheet": { "rationale": "…", "evidence": "…", "benefits": "…", "unknowns": "…", "risks": "…" },
    "repeat_warnings": {
      "heavy_rains": "…",
      "normal": "Si repites el mismo cultivo, gastas mucha más agua y cansas tu tierra.",
      "dry": "…"
    },
    "scenarios": { "normal": { "irrigation_m3": 28684.0, "irrigation_m3_per_ha": 14342.0, "risk_months": [], "risk_month_count": 0, "climate_risk": "low", "monthly": [] } }
  },
  "soil_health": {
    "condition": "tired",
    "findings": ["Lleva 3 campañas seguidas de arroz.", "Tiene poca materia orgánica."]
  },
  "risk_months": {
    "heavy_rains": ["2027-02-01", "2027-03-01"],
    "normal": [],
    "dry": []
  },
  "scenario_notes": {
    "heavy_rains": "Con lluvias fuertes, ",
    "normal": "En un año normal, ",
    "dry": "En un año seco, "
  },
  "irrigation_source": "Poechos",
  "climate_basis": {
    "source": "nasa_power",
    "variables": ["PRECTOTCORR", "T2M_MAX", "T2M_MIN"],
    "reference_years": {
      "heavy_rains": [1998, 2017, 2023],
      "normal": [2013, 2014, 2019],
      "dry": [2004, 2010, 2022]
    },
    "et0_method": "hargreaves",
    "effective_rain_fraction": 0.8,
    "risk_month_rain_mm": 150.0,
    "monthly_climate": {
      "normal": [
        { "month": 1, "rain_mm": 30.0, "t2m_max": 32.0, "t2m_min": 20.0, "et0_mm_day": 5.41, "is_risk_month": false }
      ]
    }
  },
  "example_parameters": true,
  "generated_at": "2026-11-14T15:23:42"
}
```

| Campo | Notas |
|---|---|
| `options[].scenarios` | Siempre las tres claves `heavy_rains`, `normal`, `dry` |
| `options[].excluded_by` | Ids de restricción que descartan la opción (independiente de las que envió el agricultor) |
| `options[].soil_impact` | `degrades`, `neutral`, `improves`, `improves_a_lot`, derivado de `soil_impact_score` (suma de los impactos de sus cultivos) |
| `soil_in_two_years`, `soil_health.condition`, `soil_after` | `very_tired`, `tired`, `regular`, `good` |
| `climate_risk` | `low`, `medium`, `high` |
| `ranking` | `prioridad → escenario → ids` de **todas** las opciones, de mejor a peor. Vienen **todas** las prioridades del catálogo, para que cambiar de prioridad o de escenario en la app no obligue a repetir la petición |
| `irrigation_m3` | Agua de riego de **todo el ciclo** de la rotación (ojo: `cycle_months` cambia entre opciones) |
| `risk_months` (raíz) | Meses de riesgo del horizonte de planificación, por escenario |
| `current_practice` | El último cultivo repetido `defaults.current_practice_campaigns` veces |
| `scenario_notes`, `repeat_warnings`, `irrigation_source`, `factsheet` | Textos del archivo de parámetros (decisión B11) |
| `example_parameters` | `true` mientras el JSON tenga valores de ejemplo |

**Errores**

| Código | Cuándo |
|---|---|
| `400 invalid_request` | `priority_id`, `restriction_ids` o `last_crop_id` desconocidos |
| `422 validation_error` | Campo faltante, fuera de rango o no declarado en el cuerpo |
| `502 upstream_error` | NASA POWER no devolvió datos completos para los años de referencia |
| `503 not_configured` | `agro_config.json` no se puede leer o no es coherente |

