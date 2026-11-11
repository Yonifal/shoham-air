"""Entry point.  python -m engine.run {live|forecast|train}

live      – every 15 min: pull the station, detect smoke now, alert on change
forecast  – twice a day: tonight + tomorrow night risk, daily message at ~16:00
train     – weekly: retrain on all station history + weather history
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import model, notify, ntfy, reports, station, verify, weather
from .config import (BENZENE_HEAVY, BENZENE_SMOKE, BENZENE_STRONG, DATA, LEVELS, NORTH_STATION_ID, NORTH_STATION_NAME,
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
    status = ("heavy" if bz >= BENZENE_HEAVY else "strong" if bz >= BENZENE_STRONG
              else "smoke" if bz >= BENZENE_SMOKE else "elevated" if bz >= 0.6 else "clean")
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
        rep_week = reports.week_summary(rep, now_t)
    except Exception as e:
        print("reports failed:", e)
        rep_by_hour, rep_summary, rep_week = pd.Series(dtype=int), {}, {}
    north = None
    try:
        nr = station.fetch_raw(1, NORTH_STATION_ID).dropna(subset=["PM2.5"])
        if len(nr) and nr.index[-1] >= raw.index[-1] - pd.Timedelta(hours=3):
            north = {"name": NORTH_STATION_NAME, "pm25": round(float(nr["PM2.5"].tail(3).mean()), 1),
                     "time": str(nr.index[-1] + pd.Timedelta(minutes=5))}
    except Exception as e:
        print("north station failed:", e)
    # every pollutant the unit measures: last 15 min vs the 15 min an hour earlier (for the trend arrow)
    metrics = {}
    for k in ["Benzene", "Toluene", "PM2.5", "PM10", "NO", "NO2", "O3"]:
        if k in raw:
            v = raw[k].dropna()
            if len(v):
                cur = float(v.tail(3).mean())
                ago = v[(v.index <= v.index[-1] - pd.Timedelta(minutes=55)) &
                        (v.index > v.index[-1] - pd.Timedelta(minutes=75))]
                metrics[k] = {"v": round(cur, 2), "last": round(float(v.iloc[-1]), 2),
                              "prev": None if ago.empty else round(float(ago.mean()), 2)}
    _save("live.json", {
        "metrics": metrics,
        "north": north,
        "reports": rep_summary,
        "reports_week": rep_week,
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
    s["ntfy"] = ntfy.check_thresholds(raw, s.get("ntfy", {}))
    STATE.write_text(json.dumps(s, ensure_ascii=False))
    prev = s.get("live_status", "clean")
    if status != prev:
        msg = {
            "elevated": None,
            "smoke": f"🟠 יש עשן בהדרים: בנזן {bz:.2f} מק\"ג/מ\"ק. מומלץ לסגור חלונות.",
            "strong": f"🔴 עשן משמעותי בהדרים: בנזן {bz:.2f}. סגרו חלונות.",
            "heavy": f"🔴 זיהום כבד בהדרים: בנזן {bz:.1f}. סגרו חלונות, הפעילו מטהר.",
            "clean": "🟢 האוויר בהדרים חזר לנקי. אפשר לאוורר.",
        }[status]
        # avoid flapping: announce "clean" only after a full clean hour
        if msg and (status not in ("clean", "elevated") or (raw.tail(12).Benzene < BENZENE_SMOKE).all()):
            notify.send(msg)
            s["live_status"] = status
            STATE.write_text(json.dumps(s))


LABELS = {"high": "עשן צפוי", "medium": "עשן אפשרי", "low": "לילה צפוי נקי", "uncertain": "לא ודאי"}
ORDER = {"low": 0, "uncertain": 1, "medium": 1, "high": 2}
HYST = 0.06          # a level changes only when the probability clears the threshold by this margin
UPDATE_DELTA = 0.20  # after 15:00 the published forecast changes only on a move this big


def classify(mean, lo, hi, prev=None):
    """Level from the multi-model mean and spread, with hysteresis against the previous level."""
    if hi - lo >= 0.40 and 0.15 <= mean <= 0.60:
        return "uncertain"
    raw = "high" if mean >= 0.50 else "medium" if mean >= 0.25 else "low"
    if prev in ("high", "medium", "low") and prev != raw:
        lim = {"high": 0.50, "medium": 0.25}
        # stay on the previous level unless we are clearly past the boundary
        if raw == "low" and prev == "medium" and mean > 0.25 - HYST: return prev
        if raw == "medium" and prev == "low" and mean < 0.25 + HYST: return prev
        if raw == "medium" and prev == "high" and mean > 0.50 - HYST: return prev
        if raw == "high" and prev == "medium" and mean < 0.50 + HYST: return prev
    return raw


def cmd_forecast():
    ws = weather.forecast_multi(days=3, past_days=1)
    if not ws:
        ws = {"gfs_seamless": weather.forecast(days=3, past_days=1)}
    probs = pd.DataFrame({m: model.predict(w) for m, w in ws.items()})
    mean, lo, hi = probs.mean(axis=1), probs.min(axis=1), probs.max(axis=1)
    # hourly rule for the window: share of models flagging the hour
    risk = pd.concat({m: model.hourly_risk(w) for m, w in ws.items()}, axis=1).mean(axis=1)
    now = datetime.now(IL)
    today = pd.Timestamp(now.date())
    s = _state()
    prev_levels = s.get("levels", {})
    official = s.get("official", {})
    nights = []
    for i, night in enumerate(mean.index):
        if night < today:
            continue
        key_n = str(night.date())
        m_, lo_, hi_ = float(mean[night]), float(lo[night]), float(hi[night])
        lvl = classify(m_, lo_, hi_, prev_levels.get(key_n))
        n_agree = int((probs.loc[night] >= 0.25).sum()) if lvl != "low" else int((probs.loc[night] < 0.25).sum())
        hrs = risk[(risk.index >= night + pd.Timedelta(hours=18)) & (risk.index < night + pd.Timedelta(hours=31))]
        on = hrs[hrs >= 0.5].index
        entry = {"night": key_n, "prob": round(m_, 2), "range": [round(lo_, 2), round(hi_, 2)],
                 "level": lvl, "label": LABELS[lvl], "models": {weather.MODELS[m]: round(float(v), 2)
                                                                 for m, v in probs.loc[night].items()},
                 "agree": [n_agree, len(probs.columns)], "early": night > today,
                 "window": [on.min().strftime("%H:%M"), on.max().strftime("%H:%M")] if len(on) else None}
        # after 15:00 tonight's forecast is "official": keep it unless the models moved a lot
        off = official.get(key_n)
        if off and night == today:
            if abs(m_ - off["prob"]) < UPDATE_DELTA or lvl == off["level"]:
                entry.update(level=off["level"], label=LABELS[off["level"]], window=off.get("window"))
                entry["official"] = off
            else:
                entry["official"] = off
                entry["changed"] = {"from": off["level"], "at": now.strftime("%H:%M")}
        pr = REST_BASE + REST_SLOPE * m_
        rkey, rlabel = next((k, l) for t, k, l in REST_LEVELS if pr >= t)
        entry["rest"] = {"prob": round(pr, 2), "level": rkey if lvl != "uncertain" else "uncertain",
                         "label": rlabel if lvl != "uncertain" else "לא ודאי"}
        prev_levels[key_n] = entry["level"]
        nights.append(entry)
    s["levels"] = {k: v for k, v in prev_levels.items() if k >= str(today.date())}
    tw = ws.get("gfs_seamless", next(iter(ws.values())))
    hourly = tw.assign(risk=risk)[["ws", "wd", "blh", "risk"]].round(2)
    _save("forecast.json", {
        "nights": nights,
        "hourly": [{"t": str(t), **r.to_dict()} for t, r in hourly.iterrows()],
        "updated": now.isoformat(timespec="minutes"),
    })
    if nights and nights[0]["night"] == str(today.date()) and now.hour >= 15:
        n = nights[0]
        verify.log_forecast(n["night"], n["level"], n["prob"], now.strftime("%H:%M"))
        icon = {"high": "🔴", "medium": "🟠", "low": "🟢", "uncertain": "🟡"}
        tip = {"low": "אפשר לאוורר הערב.", "uncertain": "המודלים חלוקים. כדאי להיות מוכנים ולעקוב אחרי ההתראה בזמן אמת.",
               "medium": "מומלץ לסגור חלונות בערב ולהכין מטהר.", "high": "מומלץ לסגור חלונות בערב ולהכין מטהר."}
        win = f" בין {n['window'][0]} ל-{n['window'][1]}" if n["window"] and n["level"] in ("medium", "high") else ""
        if s.get("forecast_sent") != n["night"]:
            msg = (f"{icon[n['level']]} תחזית הלילה בהדרים: {n['label']}{win} "
                   f"({n['agree'][0]} מתוך {n['agree'][1]} מודלי מזג אוויר מסכימים). {tip[n['level']]}")
            notify.send(msg)
            ntfy.forecast(msg)
            s["forecast_sent"] = n["night"]
            official[n["night"]] = {"level": n["level"], "prob": n["prob"], "window": n["window"],
                                    "issued": now.strftime("%H:%M")}
        elif n.get("changed") and s.get("update_sent") != n["night"]:
            msg = f"{icon[n['level']]} עדכון לתחזית הלילה בהדרים: {n['label']}{win}. {tip[n['level']]}"
            notify.send(msg)
            ntfy.forecast(msg)
            s["update_sent"] = n["night"]
            official[n["night"]] = {"level": n["level"], "prob": n["prob"], "window": n["window"],
                                    "issued": now.strftime("%H:%M")}
    s["official"] = {k: v for k, v in official.items() if k >= str(today.date())}
    STATE.write_text(json.dumps(s, ensure_ascii=False))


def cmd_train():
    st = pd.read_csv(DATA / "station.csv", index_col=0, parse_dates=True)
    w = weather.history(str(st.index.min().date()), str((datetime.now(IL) - timedelta(days=6)).date()))
    print(model.train(st, w))


def cmd_verify():
    def both(msg):
        notify.send(msg)
        ntfy.forecast(msg)
    print(verify.run(send=both))


if __name__ == "__main__":
    {"live": cmd_live, "forecast": cmd_forecast, "train": cmd_train, "verify": cmd_verify}[sys.argv[1]]()
