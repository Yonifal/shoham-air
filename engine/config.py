"""Shared settings for the Shoham (Hadarim) smoke forecast."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE_DATA = ROOT / "docs" / "data"

# Ministry of Environmental Protection mobile unit 5, Ha-Etrog 60, Hadarim
STATION_ID = 339
STATION_NAME = "שוהם, ניידת 5 (האתרוג 60)"
LAT, LON = 31.995, 34.955

# The Ministry reports in fixed winter time (UTC+2) all year; we use the same clock everywhere.
TZ = "Etc/GMT-2"

# Known burning areas east/south-east of Shoham (approximate)
SOURCES = {
    "נעלין": (31.952, 35.020),
    "בודרוס": (31.957, 35.030),
    "שוקבא": (31.980, 35.040),
}
# Wind blowing FROM this sector carries smoke to Hadarim (from the backtest: E and SE dominate)
TOWARD_SECTOR = (75, 170)

# Smoke definitions (µg/m³). Benzene is the burning-plastic signature.
BENZENE_SMOKE = 3.0        # hourly value that counts as a smoke hour
BENZENE_HEAVY = 8.0
BAD_NIGHT_HOURS = 3        # a night with >=3 smoke hours is a "bad night"

# Alert levels from the model's probability
LEVELS = [  # (min probability, key, Hebrew label)
    (0.50, "high", "סיכון גבוה"),
    (0.25, "medium", "סיכון"),
    (0.00, "low", "לילה צפוי נקי"),
]

WEATHER_VARS = [
    "wind_speed_10m", "wind_direction_10m", "boundary_layer_height",
    "precipitation", "temperature_2m", "relative_humidity_2m",
]
