from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CanonicalVariable(StrEnum):
    T2M_MEAN = "t2m_mean"
    T2M_MAX = "t2m_max"
    T2M_MIN = "t2m_min"
    PRECIPITATION = "precipitation"
    RH2M = "rh2m"
    SOLAR_RADIATION = "solar_radiation"
    WIND2M = "wind2m"
    NDVI = "ndvi"
    EVI = "evi"
    SOIL_MOISTURE = "soil_moisture"


class VariableSpec(BaseModel):
    name: CanonicalVariable
    unit: str
    description: str
    source_aliases: dict[str, str] = Field(default_factory=dict)


CANONICAL_VARIABLES: dict[CanonicalVariable, VariableSpec] = {
    CanonicalVariable.T2M_MEAN: VariableSpec(
        name=CanonicalVariable.T2M_MEAN,
        unit="degC",
        description="Daily mean air temperature at 2 m.",
        source_aliases={
            "power": "T2M",
            "open_meteo": "temperature_2m_mean",
            "nex_gddp": "tas",
        },
    ),
    CanonicalVariable.T2M_MAX: VariableSpec(
        name=CanonicalVariable.T2M_MAX,
        unit="degC",
        description="Daily maximum air temperature at 2 m.",
        source_aliases={
            "power": "T2M_MAX",
            "open_meteo": "temperature_2m_max",
            "nex_gddp": "tasmax",
        },
    ),
    CanonicalVariable.T2M_MIN: VariableSpec(
        name=CanonicalVariable.T2M_MIN,
        unit="degC",
        description="Daily minimum air temperature at 2 m.",
        source_aliases={
            "power": "T2M_MIN",
            "open_meteo": "temperature_2m_min",
            "nex_gddp": "tasmin",
        },
    ),
    CanonicalVariable.PRECIPITATION: VariableSpec(
        name=CanonicalVariable.PRECIPITATION,
        unit="mm/day",
        description="Daily precipitation (bias-corrected when available).",
        source_aliases={
            "power": "PRECTOTCORR",
            "open_meteo": "precipitation_sum",
            "imerg": "precipitation",
            "nex_gddp": "pr",
        },
    ),
    CanonicalVariable.RH2M: VariableSpec(
        name=CanonicalVariable.RH2M,
        unit="%",
        description="Daily mean relative humidity at 2 m.",
        source_aliases={
            "power": "RH2M",
        },
    ),
    CanonicalVariable.SOLAR_RADIATION: VariableSpec(
        name=CanonicalVariable.SOLAR_RADIATION,
        unit="MJ/m^2/day",
        description="All-sky surface shortwave downward irradiance.",
        source_aliases={
            "power": "ALLSKY_SFC_SW_DWN",
            "open_meteo": "shortwave_radiation_sum",
        },
    ),
    CanonicalVariable.WIND2M: VariableSpec(
        name=CanonicalVariable.WIND2M,
        unit="m/s",
        description="Daily mean wind speed at 2 m.",
        source_aliases={
            "power": "WS2M",
            "open_meteo": "wind_speed_10m_max",
        },
    ),
    CanonicalVariable.NDVI: VariableSpec(
        name=CanonicalVariable.NDVI,
        unit="index",
        description="Normalized Difference Vegetation Index (-1 to 1).",
        source_aliases={"appeears_modis": "_250m_16_days_NDVI", "appeears_viirs": "NDVI"},
    ),
    CanonicalVariable.EVI: VariableSpec(
        name=CanonicalVariable.EVI,
        unit="index",
        description="Enhanced Vegetation Index.",
        source_aliases={"appeears_modis": "_250m_16_days_EVI"},
    ),
    CanonicalVariable.SOIL_MOISTURE: VariableSpec(
        name=CanonicalVariable.SOIL_MOISTURE,
        unit="m^3/m^3",
        description="Surface soil moisture (volumetric).",
        source_aliases={"appeears_smap": "soil_moisture"},
    ),
}
