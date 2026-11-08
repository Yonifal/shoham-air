"""Weather history and forecast from Open-Meteo (free, no key)."""
import pandas as pd
import requests

from .config import LAT, LON, TZ, WEATHER_VARS

RENAME = {
    "wind_speed_10m": "ws", "wind_direction_10m": "wd", "boundary_layer_height": "blh",
    "precipitation": "prcp", "temperature_2m": "temp", "relative_humidity_2m": "rh",
}


def _get(url, params):
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    df = pd.DataFrame(h)
    df.index = pd.to_datetime(df.pop("time"))
    return df.rename(columns=RENAME)


def history(start: str, end: str) -> pd.DataFrame:
    return _get("https://archive-api.open-meteo.com/v1/archive", {
        "latitude": LAT, "longitude": LON, "start_date": start, "end_date": end,
        "hourly": ",".join(WEATHER_VARS), "wind_speed_unit": "ms", "timezone": TZ,
    })


def forecast(days: int = 3, past_days: int = 2) -> pd.DataFrame:
    params = {
        "latitude": LAT, "longitude": LON, "hourly": ",".join(WEATHER_VARS),
        "wind_speed_unit": "ms", "timezone": TZ, "forecast_days": days, "past_days": past_days,
    }
    df = _get("https://api.open-meteo.com/v1/forecast", params)
    # Not every model publishes mixing height; fall back to GFS for that one variable.
    if df["blh"].isna().mean() > 0.5:
        g = _get("https://api.open-meteo.com/v1/forecast",
                 {**params, "hourly": "boundary_layer_height", "models": "gfs_seamless"})
        df["blh"] = g["blh"].reindex(df.index)
    return df
