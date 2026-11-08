"""Entry point.  python -m engine.run {live|forecast|train}

live      – every 15 min: pull the station, detect smoke now, alert on change
forecast  – twice a day: tonight + tomorrow night risk, daily message at ~16:00
train     – weekly: retrain on all station history + weather history
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import model, notify, reports, station, weather
from .config import (BENZENE_HEAVY, BENZENE_SMOKE, DATA, LEVELS, NORTH_STATION_ID, NORTH_STATION_NAME,
                     REST_BASE, REST_LEVELS, REST_SLOPE, SITE_DATA, STATION_NAME)

STATE = DATA / "state.json"
IL = timezone(timedelta(hours=2))


def _state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save(name, obj):
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def level(p):
    for thr, key, label in LEVELS:
        if p >= thr:
            return key, label


def cmd_live():
    st, raw = station.update_archive(days_back=2)
    raw = raw.dropna(subset=["Benzene"])
    now15 = raw.tail(3)                       # last 15 minutes of 5-min readings
    bz = float(now15.Benzene.mean())
    pm = now15["PM2.5"].mean()
    status = "heavy" if bz >= BENZENE_HEAVY else "smoke" if bz >= BENZENE_SMOKE else "clean"
    # 48 whole hours ending with the current (possibly partial) hour
    cur_hour = raw.index[-1].floor("h")
    hist = st[(st.index > cur_hour - pd.Timedelta(hours=48)) & (st.index < cur_hour)]
    partial = raw[raw.index >= cur_hour].mean(numeric_only=True)
    hist = pd.concat([hist, partial.to_frame(cur_hour).T])
    hist = hist.reindex(pd.date_range(cur_hour - pd.Timedelta(hours=47), cur_hour, freq="h"))
    now_t = raw.index[-1] + pd.Timedelta(minutes=5)
    try:  # residents' reports must never break the station check
        rep = reports.sync()
        if not rep.empty:
            reports.device_reliability(rep, st).round(2).to_csv(DATA / "device_reliability.csv")
        rep_by_hour = rep.time.dt.floor("h").value_counts() if not rep.empty else pd.Series(dtype=int)
        rep_summary = reports.recent_summary(rep, now_t)
    except Exception as e:
        print("reports failed:", e)
        rep_by_hour, rep_summary = pd.Series(dtype=int), {}
    north = None
    try:
        nr = station.fetch_raw(1, NORTH_STATION_ID).dropna(subset=["PM2.5"])
        if len(nr) and nr.index[-1] >= raw.index[-1] - pd.Timedelta(hours=3):
            north = {"name": NORTH_STATION_NAME, "pm25": round(float(nr["PM2.5"].tail(3).mean()), 1),
                     "time": str(nr.index[-1] + pd.Timedelta(minutes=5))}
    except Exception as e:
        print("north station failed:", e)
    _save("live.json", {
        "north": north,
        "reports": rep_summary,
        "station": STATION_NAME, "time": str(raw.index[-1] + pd.Timedelta(minutes=5)),
        "status": status, "benzene": round(bz, 2),
        "pm25": None if pd.isna(pm) else round(float(pm), 1),
        "last48": [{"t": str(t), "bz": None if pd.isna(r.Benzene) else round(float(r.Benzene), 2),
                    "pm": None if pd.isna(r["PM2.5"]) else round(float(r["PM2.5"]), 1),
                    "rep": int(rep_by_hour.get(t, 0))}
                   for t, r in hist.iterrows()],
        "updated": datetime.now(IL).isoformat(timespec="minutes"),
    })
    s = _state()
    prev = s.get("live_status", "clean")
    if status != prev:
        msg = {
            "smoke": f"🟠 העשן הגיע להדרים: בנזן {bz:.1f} מק\"ג/מ\"ק. מומלץ לסגור חלונות.",
            "heavy": f"🔴 זיהום כבד בהדרים: בנזן {bz:.1f}. סגרו חלונות, הפעילו מטהר.",
            "clean": "🟢 האוויר בהדרים חזר לנקי. אפשר לאוורר.",
        }[status]
        # avoid flapping: announce "clean" only after a full clean hour
        if status != "clean" or (raw.tail(12).Benzene < BENZENE_SMOKE).all():
            notify.send(msg)
            s["live_status"] = status
            STATE.write_text(json.dumps(s))


def cmd_forecast():
    w = weather.forecast(days=3, past_days=1)
    p = model.predict(w)
    risk = model.hourly_risk(w)
    today = pd.Timestamp(datetime.now(IL).date())
    nights = []
    for night, prob in p.items():
        if night < today:
            continue
        key, label = level(prob)
        hrs = risk[(risk.index >= night + pd.Timedelta(hours=18)) &
                   (risk.index < night + pd.Timedelta(hours=31))]
        on = hrs[hrs == 1].index
        pr = REST_BASE + REST_SLOPE * float(prob)
        rkey, rlabel = next((k, l) for t, k, l in REST_LEVELS if pr >= t)
        nights.append({"night": str(night.date()), "prob": round(float(prob), 2), "level": key,
                       "label": label, "rest": {"prob": round(pr, 2), "level": rkey, "label": rlabel},
                       "window": [str(on.min().strftime("%H:%M")), str(on.max().strftime("%H:%M"))]
                       if len(on) else None})
    hourly = w.assign(risk=risk)[["ws", "wd", "blh", "risk"]].round(1)
    _save("forecast.json", {
        "nights": nights,
        "hourly": [{"t": str(t), **r.to_dict()} for t, r in hourly.iterrows()],
        "updated": datetime.now(IL).isoformat(timespec="minutes"),
    })
    s = _state()
    if nights and s.get("forecast_sent") != nights[0]["night"] and datetime.now(IL).hour >= 15:
        n = nights[0]
        icon = {"high": "🔴", "medium": "🟠", "low": "🟢"}[n["level"]]
        win = f" בין {n['window'][0]} ל-{n['window'][1]}" if n["window"] and n["level"] != "low" else ""
        tip = "אפשר לאוורר הערב." if n["level"] == "low" else "מומלץ לסגור חלונות בערב ולהכין מטהר."
        notify.send(f"{icon} תחזית הלילה בהדרים: {n['label']}{win} ({int(n['prob']*100)}%). {tip}")
        s["forecast_sent"] = n["night"]
        STATE.write_text(json.dumps(s))


def cmd_train():
    st = pd.read_csv(DATA / "station.csv", index_col=0, parse_dates=True)
    w = weather.history(str(st.index.min().date()), str((datetime.now(IL) - timedelta(days=6)).date()))
    print(model.train(st, w))


if __name__ == "__main__":
    {"live": cmd_live, "forecast": cmd_forecast, "train": cmd_train}[sys.argv[1]]()
