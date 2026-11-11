"""Night-level smoke model: features, labels, training and prediction."""
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .config import BAD_NIGHT_HOURS, BENZENE_SMOKE, BENZENE_STRONG, DATA, TOWARD_SECTOR

FEATURES = ["u", "v", "ws", "blh", "blh_min", "tow", "prcp", "rh", "temp", "doy_s", "doy_c"]
MODEL_PATH = DATA / "model.joblib"                # smoke night: benzene >1 for 3+ hours
STRONG_PATH = DATA / "model_strong.joblib"        # strong-smoke night: benzene >3 for 3+ hours


def night_of(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Night D = 18:00 on D until 06:59 on D+1."""
    return pd.to_datetime((idx - pd.Timedelta(hours=12)).date)


def is_night(idx: pd.DatetimeIndex):
    return (idx.hour >= 18) | (idx.hour <= 6)


def hourly_risk(w: pd.DataFrame) -> pd.Series:
    """Simple transparent rule per hour: wind from the burning sites + trapped air + weak wind."""
    lo, hi = TOWARD_SECTOR
    return (w.wd.between(lo, hi) & (w.blh < 150) & (w.ws < 4)).astype(int)


def night_features(w: pd.DataFrame) -> pd.DataFrame:
    w = w[is_night(w.index)].copy()
    r = np.deg2rad(w.wd)
    w["u"], w["v"] = -w.ws * np.sin(r), -w.ws * np.cos(r)
    lo, hi = TOWARD_SECTOR
    w["tow"] = w.wd.between(lo, hi).astype(float)
    w["night"] = night_of(w.index)
    f = w.groupby("night").agg(
        u=("u", "mean"), v=("v", "mean"), ws=("ws", "mean"), blh=("blh", "mean"),
        blh_min=("blh", "min"), tow=("tow", "mean"), prcp=("prcp", "sum"),
        rh=("rh", "mean"), temp=("temp", "mean"), hours=("ws", "size"))
    doy = f.index.dayofyear
    f["doy_s"], f["doy_c"] = np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365)
    return f


def night_labels(st: pd.DataFrame, thr: float = BENZENE_SMOKE) -> pd.DataFrame:
    s = st[is_night(st.index) & st.Benzene.notna()].copy()
    s["night"] = night_of(s.index)
    g = s.groupby("night").agg(n=("Benzene", "size"), bz_max=("Benzene", "max"),
                               smoke_hours=("Benzene", lambda x: int((x > thr).sum())))
    g = g[g.n >= 10]
    g["bad"] = g.smoke_hours >= BAD_NIGHT_HOURS
    return g


def train(st: pd.DataFrame, w: pd.DataFrame) -> dict:
    info = {}
    for path, thr, key in [(MODEL_PATH, BENZENE_SMOKE, "smoke"), (STRONG_PATH, BENZENE_STRONG, "strong")]:
        X = night_features(w).join(night_labels(st, thr), how="inner")
        clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                             min_samples_leaf=15, random_state=0)
        clf.fit(X[FEATURES], X.bad)
        joblib.dump(clf, path)
        info[key] = {"nights": int(len(X)), "bad_nights": int(X.bad.sum())}
    info["trained_until"] = str(X.index.max().date())
    (DATA / "model_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    return info


def predict(w: pd.DataFrame, strong: bool = False) -> pd.Series:
    clf = joblib.load(STRONG_PATH if strong else MODEL_PATH)
    f = night_features(w)
    f = f[f.hours >= 10]
    return pd.Series(clf.predict_proba(f[FEATURES])[:, 1], index=f.index)
