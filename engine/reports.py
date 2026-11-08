"""Residents' "smells like smoke" reports, collected by a Google Apps Script web app (reports/Code.gs).

Safeguards against noise or abuse:
- each browser has an anonymous random id (sent as note "d:<id>"); one report per 30 min per device on the site
- a neighbourhood counts as a *confirmed* event only when CONFIRM_DEVICES different devices report
  within CONFIRM_MINUTES
- each device gets a reliability score from how its Hadarim reports match the monitoring unit
- reports never trigger alerts; they are shown separately from measurements
"""
import os

import pandas as pd
import requests

from .config import BENZENE_SMOKE, CONFIRM_DEVICES, CONFIRM_MINUTES, DATA, REPORTS_URL

URL = os.getenv("REPORTS_URL") or REPORTS_URL


def sync(days: int = 30) -> pd.DataFrame:
    """Merge recent reports into data/reports.csv (times stored as UTC+2, like the station)."""
    path = DATA / "reports.csv"
    cols = ["time", "hood", "level", "device"]
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=cols)
    old["time"] = pd.to_datetime(old["time"])
    if not URL:
        return old
    try:
        rows = requests.get(URL, params={"days": days}, timeout=30).json().get("reports", [])
    except Exception as e:  # reporting must never break the station check
        print("reports sync failed:", e)
        return old
    new = pd.DataFrame(rows)
    if new.empty:
        return old
    new["time"] = pd.to_datetime(new.t, utc=True).dt.tz_convert("Etc/GMT-2").dt.tz_localize(None)
    new["device"] = new.note.astype(str).str.extract(r"d:([a-z0-9]+)", expand=False).fillna("unknown")
    new = new[cols]
    allr = pd.concat([old, new])
    allr["time"] = pd.to_datetime(allr.time)
    allr = allr.drop_duplicates(subset=["time", "hood", "device"]).sort_values("time")
    allr.to_csv(path, index=False)
    return allr


def device_reliability(allr: pd.DataFrame, station: pd.DataFrame) -> pd.Series:
    """Share of a device's Hadarim reports made while benzene was elevated (≥ half the smoke threshold).
    Devices without Hadarim reports get a neutral 0.5."""
    h = allr[allr.hood == "הדרים"].copy()
    if h.empty:
        return pd.Series(dtype=float)
    bz = station.Benzene.reindex(h.time.dt.floor("h")).to_numpy()
    h["match"] = bz >= BENZENE_SMOKE / 2
    g = h.groupby("device").match.agg(["mean", "size"])
    # shrink toward 0.5 until a device has a few reports
    return (g["mean"] * g["size"] + 0.5 * 3) / (g["size"] + 3)


def recent_summary(allr: pd.DataFrame, now: pd.Timestamp, hours: int = 3) -> dict:
    """Per neighbourhood: reports in the last few hours, distinct devices, and whether it is confirmed."""
    if allr.empty:
        return {}
    r = allr[allr.time >= now - pd.Timedelta(hours=hours)]
    out = {}
    for hood, g in r.groupby("hood"):
        g = g.sort_values("time")
        confirmed = any(
            g[(g.time >= t) & (g.time <= t + pd.Timedelta(minutes=CONFIRM_MINUTES))].device.nunique()
            >= CONFIRM_DEVICES for t in g.time)
        out[hood] = {"n": int(len(g)), "devices": int(g.device.nunique()),
                     "max": int(g.level.max()), "confirmed": bool(confirmed)}
    return out
