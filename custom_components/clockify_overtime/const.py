"""Constants for the Clockify Overtime Tracker integration."""

DOMAIN = "clockify_overtime"

API_BASE_URL = "https://api.clockify.me/api/v1"

# Config entry keys
CONF_API_KEY = "api_key"
CONF_TRACKING_MODE = "tracking_mode"
CONF_EXCLUDED_PROJECT_IDS = "excluded_project_ids"
CONF_HOURS_PER_WEEK = "hours_per_week"
CONF_WORKING_DAYS = "working_days"
CONF_START_DATE = "start_date"
CONF_CORRECTION_HOURS = "correction_hours"
CONF_SCAN_INTERVAL = "scan_interval"

# Tracking modes
TRACKING_MODE_ALL = "all"
TRACKING_MODE_BILLABLE = "billable"

# Defaults
DEFAULT_HOURS_PER_WEEK = 40.0
DEFAULT_SCAN_INTERVAL = 30  # minutes
DEFAULT_TRACKING_MODE = TRACKING_MODE_ALL
DEFAULT_CORRECTION_HOURS = 0.0

PLATFORMS = ["sensor", "number"]

# Weekday name → Python weekday number (Monday=0)
WEEKDAY_MAP = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}

DEFAULT_WORKING_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]
