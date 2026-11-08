"""Live readings from the Ministry's air-monitoring API (via the open-source air-sviva-api client)."""
import asyncio
from datetime import date, timedelta

import aiohttp
import pandas as pd
from air_sviva_api.client import SvivaAirClient

from .config import DATA, STATION_ID

KEEP = ["Benzene", "Toluene", "PM2.5", "PM10", "NO2", "NOX", "NO", "O3"]


async def _fetch(days_back: int, timebase: int, station_id: int = STATION_ID) -> pd.DataFrame:
    async with aiohttp.ClientSession() as s:
        c = SvivaAirClient(s)
        await c.generate_token()
        resp = await c.get_station_average(
            station_id, from_date=date.today() - timedelta(days=days_back),
            to_date=date.today(), timebase=timebase)
    rows = []
    for p in resp.data or []:
        row = {"time": p.datetime}
        for ch in p.channels or []:
            if ch.name in KEEP:
                row[ch.name] = ch.value if ch.valid else None
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # API timestamps mark the END of the averaging window; store the window start, naive UTC+2
    t = pd.to_datetime(df.pop("time"))
    if t.dt.tz is not None:
        t = t.dt.tz_convert("Etc/GMT-2").dt.tz_localize(None)
    df.index = t - pd.Timedelta(minutes=timebase)
    return df.sort_index()


def fetch_raw(days_back: int = 1, station_id: int = STATION_ID) -> pd.DataFrame:
    """5-minute readings (the API returns 5-min data regardless of the requested timebase).
    It also pads the rest of today with empty rows, which we drop."""
    return asyncio.run(_fetch(days_back, 5, station_id)).dropna(how="all")


def hourly(raw: pd.DataFrame) -> pd.DataFrame:
    """Hourly means, kept only when at least half the 5-min readings exist (like the Ministry's 'valid hour')."""
    g = raw.resample("h")
    means, counts = g.mean(), g.count()
    return means.where(counts >= 6).dropna(how="all")


def update_archive(days_back: int = 2):
    """Merge fresh hourly values into data/station.csv. Returns (hourly archive, latest 5-min readings)."""
    path = DATA / "station.csv"
    old = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else pd.DataFrame()
    if not old.empty:  # keep only whole-hour rows (cleans up any earlier 5-min rows)
        old = old[(old.index.minute == 0)]
    raw = fetch_raw(days_back)
    new = hourly(raw)
    allx = new.combine_first(old) if not old.empty else new  # fresh values win, gaps keep old ones
    allx = allx.dropna(how="all").sort_index().round(2)
    allx.to_csv(path)
    return allx, raw
