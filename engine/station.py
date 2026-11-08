"""Live readings from the Ministry's air-monitoring API (via the open-source air-sviva-api client)."""
import asyncio
from datetime import date, timedelta

import aiohttp
import pandas as pd
from air_sviva_api.client import SvivaAirClient

from .config import DATA, STATION_ID

KEEP = ["Benzene", "Toluene", "PM2.5", "PM10", "NO2", "NOX", "NO", "O3"]


async def _fetch(days_back: int, timebase: int) -> pd.DataFrame:
    async with aiohttp.ClientSession() as s:
        c = SvivaAirClient(s)
        await c.generate_token()
        resp = await c.get_station_average(
            STATION_ID, from_date=date.today() - timedelta(days=days_back),
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


def fetch(days_back: int = 1, timebase: int = 60) -> pd.DataFrame:
    return asyncio.run(_fetch(days_back, timebase))


def update_archive(days_back: int = 2) -> pd.DataFrame:
    """Append the latest hourly values to data/station.csv and return the full archive."""
    path = DATA / "station.csv"
    old = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else pd.DataFrame()
    new = fetch(days_back, 60)
    allx = pd.concat([old, new])
    allx = allx[~allx.index.duplicated(keep="last")].sort_index()
    allx.to_csv(path)
    return allx
