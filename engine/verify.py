"""Morning check: was last night's official forecast right?"""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import BAD_NIGHT_HOURS, BENZENE_SMOKE, DATA, SITE_DATA

IL = timezone(timedelta(hours=2))
LOG = DATA / "forecast_log.csv"      # one row per night: the forecast we stood behind (15:00)
VER = DATA / "verification.csv"      # one row per night: forecast vs measured
NAMES = {"high": "סיכון גבוה", "medium": "סיכון", "low": "לילה נקי", "uncertain": "לא ודאי"}


def log_forecast(night: str, level: str, prob: float, issued: str, note: str = ""):
    old = pd.read_csv(LOG, dtype=str) if LOG.exists() else pd.DataFrame()
    if not old.empty and night in set(old.night):
        return
    row = pd.DataFrame([{"night": night, "level": level, "prob": prob, "issued": issued, "note": note}])
    pd.concat([old, row]).to_csv(LOG, index=False)


def judge(level: str, bad: bool) -> tuple:
    if level == "uncertain":
        return "open", "לא התחייבנו (המודלים היו חלוקים)"
    if level in ("high", "medium"):
        return ("hit", "צדקנו: היה עשן") if bad else ("false_alarm", "התרענו לשווא: הלילה היה נקי")
    return ("hit", "צדקנו: הלילה היה נקי") if not bad else ("miss", "פספסנו: היה עשן ולא חזינו")


def run(send=None):
    now = datetime.now(IL)
    if now.hour < 7:  # the night is not over yet
        return None
    night = (now - timedelta(days=1)).date().isoformat()
    done = pd.read_csv(VER, dtype=str) if VER.exists() else pd.DataFrame(columns=["night"])
    if night in set(done.night):
        return None
    if not LOG.exists():
        return None
    log = pd.read_csv(LOG, dtype=str).set_index("night")
    if night not in log.index:
        return None
    st = pd.read_csv(DATA / "station.csv", index_col=0, parse_dates=True)
    t0 = pd.Timestamp(night) + pd.Timedelta(hours=18)
    bz = st.loc[t0: t0 + pd.Timedelta(hours=12, minutes=59), "Benzene"].dropna()
    if len(bz) < 10:
        return None  # not enough data yet; try again on the next run
    smoke_h = int((bz > BENZENE_SMOKE).sum())
    bad = smoke_h >= BAD_NIGHT_HOURS
    f = log.loc[night]
    outcome, text = judge(f.level, bad)
    peak_t = bz.idxmax()
    row = {"night": night, "forecast": f.level, "prob": f.prob, "issued": f.issued, "smoke_hours": smoke_h,
           "bz_max": round(float(bz.max()), 2), "peak": peak_t.strftime("%H:%M"), "bad": bad,
           "outcome": outcome, "note": f.get("note", "")}
    allv = pd.concat([done, pd.DataFrame([row])])
    allv.to_csv(VER, index=False)

    scored = allv[allv.outcome.isin(["hit", "false_alarm", "miss"])]
    stats = {"nights": int(len(allv)), "scored": int(len(scored)),
             "hits": int((scored.outcome == "hit").sum()),
             "false_alarms": int((scored.outcome == "false_alarm").sum()),
             "misses": int((scored.outcome == "miss").sum()),
             "open": int((allv.outcome == "open").sum())}
    last = {**row, "text": text, "forecast_label": NAMES.get(f.level, f.level)}
    (SITE_DATA / "verify.json").write_text(json.dumps(
        {"last": last, "stats": stats, "history": allv.tail(14).to_dict("records"),
         "updated": now.isoformat(timespec="minutes")}, ensure_ascii=False, indent=1, default=str))

    icon = {"hit": "✅", "false_alarm": "⚠️", "miss": "❌", "open": "🟡"}[outcome]
    measured = (f"{smoke_h} שעות עשן, שיא בנזן {row['bz_max']} ב-{row['peak']}" if bad
                else f"בלי שעות עשן (שיא בנזן {row['bz_max']})" if smoke_h == 0
                else f"{smoke_h} שעות עשן קצרות, שיא בנזן {row['bz_max']}")
    msg = (f"{icon} בדיקת הבוקר, הלילה שעבר בהדרים:\n"
           f"התחזית מ-{f.issued}: {NAMES.get(f.level, f.level)}\n"
           f"בפועל: {measured}\n{text}.\n"
           f"מאז שהתחלנו: {stats['hits']} מתוך {stats['scored']} נכונות"
           + ("" if not stats['false_alarms'] else ", התרעת שווא אחת" if stats['false_alarms'] == 1
              else f", {stats['false_alarms']} התרעות שווא")
           + ("" if not stats['misses'] else ", פספוס אחד" if stats['misses'] == 1
              else f", {stats['misses']} פספוסים") + ".")
    if send:
        send(msg)
    return msg
