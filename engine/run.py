"""Entry point.  python -m engine.run {live|forecast|train}

live      – every 15 min: pull the station, detect smoke now, alert on change
forecast  – twice a day: tonight + tomorrow night risk, daily message at ~16:00
train     – weekly: retrain on all station history + weather history
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import model, notify, station, weather
from .config import BENZENE_HEAVY, BENZENE_SMOKE, DATA, LEVELS, SITE_DATA, STATION_NAME

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
    st = station.update_archive(days_back=2)
    recent = st.dropna(subset=["Benzene"]).tail(3)
    last = recent.iloc[-1]
    bz = float(last.Benzene)
    status = "heavy" if bz >= BENZENE_HEAVY else "smoke" if bz >= BENZENE_SMOKE else "clean"
    hist = st.tail(48)
    _save("live.json", {
        "station": STATION_NAME, "time": str(recent.index[-1] + pd.Timedelta(hours=1)),
        "status": status, "benzene": round(bz, 2),
        "pm25": None if pd.isna(last.get("PM2.5")) else round(float(last["PM2.5"]), 1),
        "last48": [{"t": str(t), "bz": None if pd.isna(r.Benzene) else round(r.Benzene, 2),
                    "pm": None if pd.isna(r["PM2.5"]) else round(r["PM2.5"], 1)}
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
        # avoid flapping: announce "clean" only after 2 consecutive clean hours
        if status != "clean" or (recent.Benzene.tail(2) < BENZENE_SMOKE).all():
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
        nights.append({"night": str(night.date()), "prob": round(float(prob), 2), "level": key,
                       "label": label,
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
