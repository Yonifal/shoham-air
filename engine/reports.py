"""Residents' "smells like smoke" reports, collected by a Google Apps Script web app (reports/Code.gs)."""
import os

import pandas as pd
import requests

from .config import DATA

URL = os.getenv("REPORTS_URL", "")


def sync(days: int = 30) -> pd.DataFrame:
    """Merge recent reports into data/reports.csv (times stored as UTC+2, like the station)."""
    path = DATA / "reports.csv"
    old = pd.read_csv(path, parse_dates=["time"]) if path.exists() else pd.DataFrame(
        columns=["time", "hood", "level", "note"])
    if not URL:
        return old
    try:
        rows = requests.get(URL, params={"days": days}, timeout=30).json().get("reports", [])
    except Exception as e:  # reporting must never break the station check
        print("reports sync failed:", e)
        return old
    new = pd.DataFrame(rows).rename(columns={"t": "time"})
    if new.empty:
        return old
    new["time"] = pd.to_datetime(new.time, utc=True).dt.tz_convert("Etc/GMT-2").dt.tz_localize(None)
    allr = pd.concat([old, new]).drop_duplicates(subset=["time", "hood", "level"]).sort_values("time")
    allr.to_csv(path, index=False)
    return allr


def recent_summary(allr: pd.DataFrame, now: pd.Timestamp, hours: int = 3) -> dict:
    """Count of reports per neighbourhood in the last few hours, for the site."""
    if allr.empty:
        return {}
    r = allr[allr.time >= now - pd.Timedelta(hours=hours)]
    return {h: {"n": int(len(g)), "max": int(g.level.max())} for h, g in r.groupby("hood")}
