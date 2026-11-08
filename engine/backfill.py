"""One-off: pull hourly history of stations around Shoham (to learn what reaches north Shoham).

python -m engine.backfill 2025-12-01
Writes data/neighbors/<station_id>.csv (hourly means) and data/neighbors/stations.csv.
"""
import asyncio
import sys
from datetime import date, timedelta

import aiohttp
import pandas as pd
from air_sviva_api.client import SvivaAirClient

from .config import DATA
from .station import hourly

NAMES = ["שוהם", "ראש העין", "מודיעין", "בית חשמונאי", "אלעד", "יהוד", "אור יהודה", "לוד", "רמלה"]
KEEP = ["Benzene", "Toluene", "PM2.5", "PM10", "NO2", "WD", "WS"]
OUT = DATA / "neighbors"


async def main(start: date):
    OUT.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as s:
        c = SvivaAirClient(s)
        await c.generate_token()
        regions = await c.get_regions()
        stations = [st for r in regions for st in (r.stations or [])
                    if any(n in (st.name or "") for n in NAMES)]
        meta = []
        for st in stations:
            loc = st.location
            meta.append({"id": st.station_id, "name": st.name, "active": st.active, "mobile": st.mobile,
                         "lat": getattr(loc, "latitude", None), "lon": getattr(loc, "longitude", None),
                         "monitors": ",".join(m.name for m in (st.monitors or []) if getattr(m, "name", None))})
        pd.DataFrame(meta).to_csv(OUT / "stations.csv", index=False)
        print(pd.DataFrame(meta).to_string())

        for st in stations:
            frames, d = [], start
            while d <= date.today():
                d2 = min(d + timedelta(days=6), date.today())
                try:
                    resp = await c.get_station_average(st.station_id, from_date=d, to_date=d2, timebase=5)
                    rows = []
                    for p in resp.data or []:
                        row = {"time": p.datetime}
                        for ch in p.channels or []:
                            if ch.name in KEEP:
                                row[ch.name] = ch.value if ch.valid else None
                        rows.append(row)
                    if rows:
                        df = pd.DataFrame(rows)
                        t = pd.to_datetime(df.pop("time"))
                        if t.dt.tz is not None:
                            t = t.dt.tz_convert("Etc/GMT-2").dt.tz_localize(None)
                        df.index = t - pd.Timedelta(minutes=5)
                        frames.append(df.dropna(how="all"))
                except Exception as e:
                    print(st.station_id, d, "failed:", e)
                d = d2 + timedelta(days=1)
                await asyncio.sleep(0.3)
            if frames:
                h = hourly(pd.concat(frames).sort_index()).round(2)
                h.to_csv(OUT / f"{st.station_id}.csv")
                print(st.station_id, st.name, len(h), "hours", list(h.columns))


if __name__ == "__main__":
    asyncio.run(main(date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2025-12-01")))
