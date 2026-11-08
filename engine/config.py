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

# Permanent Ministry station in central/north Shoham (PM2.5 and PM10 only, no benzene)
NORTH_STATION_ID = 598
NORTH_STATION_NAME = "שוהם, תחנה קבועה (מרכז-צפון)"

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

# Residents' reports endpoint (Google Apps Script web app, see reports/Code.gs). Public by design.
REPORTS_URL = "https://script.google.com/macros/s/AKfycbzHwwyeOOYUARlirW-TghWBI7UMS-7Agdvi8SZ_wCMEan_Exriqc5IOzJ2_GiGblkVUSQ/exec"
CONFIRM_DEVICES = 3        # distinct devices in the same neighbourhood…
CONFIRM_MINUTES = 30       # …within this window = a confirmed smoke event

# Rest of Shoham (no benzene measurement there). From Dec 2025–Nov 2026 history of the permanent
# central/north station (598, PM2.5): a "bad night" there followed 33% of Hadarim bad nights and 13%
# of Hadarim clean nights. So:  p_rest ≈ REST_BASE + REST_SLOPE · p_hadarim
REST_BASE, REST_SLOPE = 0.13, 0.20
REST_LEVELS = [(0.22, "medium", "סיכון"), (0.0, "low", "סיכון נמוך")]
