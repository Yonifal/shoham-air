"""Push alerts through ntfy.sh topics: one topic per threshold, people subscribe to the ones they want."""
import requests

from .config import NTFY_FORECAST, NTFY_PREFIX, NTFY_THRESHOLDS

SITE = "https://yonifal.github.io/shoham-air/"
NAMES = {"Benzene": "בנזן", "PM2.5": "PM2.5"}


def fmt(x: float) -> str:
    """Up to 2 decimals, no padding (0.88 stays 0.88, 20.0 becomes 20)."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def topic(key: str) -> str:
    return f"{NTFY_PREFIX}-{key}"


REPORT_LINK = SITE + "docs/#now"   # the Now tab has the one-tap report and the morning question


def publish(key: str, title: str, message: str, priority: int = 3, tags=None, click: str = SITE):
    try:
        requests.post("https://ntfy.sh/", json={
            "topic": topic(key), "title": title, "message": message, "priority": priority,
            "tags": tags or [], "click": click}, timeout=20)
    except Exception as e:  # alerts must never break the station check
        print("ntfy failed:", e)


def check_thresholds(raw, state: dict) -> dict:
    """Send 'crossed up' / 'back down' per threshold, using the 15-min mean with hysteresis.
    raw: 5-min readings (DataFrame). state: {key: bool above}. Returns the updated state."""
    for key, (col, thr, label) in NTFY_THRESHOLDS.items():
        if col not in raw:
            continue
        v = raw[col].dropna()
        if len(v) < 3:
            continue
        mean15, last = float(v.tail(3).mean()), float(v.iloc[-1])
        above = state.get(key, False)
        name = NAMES.get(col, col)
        if not above and mean15 >= thr:
            heavy = thr >= 3 if col == "Benzene" else thr >= 37.5
            publish(key, f"{name} עלה מעל {thr:g} בהדרים",
                    f"{name} עכשיו {fmt(last)} מק\"ג/מ\"ק (ממוצע רבע שעה {fmt(mean15)}). "
                    + ("מומלץ לסגור חלונות." if heavy else "שווה לעקוב.")
                    + " מריחים אצלכם? לחצו על ההתראה ודווחו בלחיצה אחת.",
                    priority=4 if heavy else 3, tags=["warning"], click=REPORT_LINK)
            state[key] = True
        elif above and len(v) >= 6 and float(v.tail(6).max()) < thr:  # 30 minutes (6 readings) below the line
            hour = v.index[-1].hour
            night = hour >= 17 or hour < 9
            if night:
                tail = ("ירידה זמנית: בלילות כאלה הזיהום מגיע בגלים, והנתונים מהניידת מגיעים באיחור. "
                        "עדיף להשאיר חלונות סגורים עד הבוקר.")
            else:
                tail = "אפשר לאוורר." if col == "Benzene" else ""
            publish(key, f"{name} ירד מתחת ל-{thr:g} בהדרים",
                    f"{name} עכשיו {fmt(last)} מק\"ג/מ\"ק. " + tail,
                    priority=2, tags=["arrow_down"] if night else ["white_check_mark"])
            state[key] = False
    return state


def forecast(text: str, ask_night: bool = False):
    if ask_night:
        text += "\n☀️ איך היה הלילה אצלכם? לחצו כאן וספרו בלחיצה אחת."
    publish(NTFY_FORECAST, "אוויר בשוהם", text, priority=3, tags=["cloud"], click=REPORT_LINK if ask_night else SITE)
