from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv



BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

VALID_LOG_LEVELS = {"DEBUG", 
                    "INFO", 
                    "WARNING", 
                    "ERROR", 
                    "CRITICAL"}

PLACEHOLDERS = {
    "GARMIN_PERSONAL_API_KEY": "api_key",
    "DATABASE_URL": "user:pass"
}

class ConfigError(RuntimeError):
    """Raised when config is missing or invalid"""


@dataclass(frozen=True)
class Settings:
    garmin_api_key: str = field(repr=False)
    database_url: str | None = field(repr=False)
    latitude: float
    longitide: float
    timezone: ZoneInfo
    log_level: str
    base_dir: Path = BASE_DIR

    @property
    def raw_data_dir(self) -> Path:
        return self.base_dir / "data" / "raw"

    @property
    def log_dir(self) -> Path:
        return self.base_dir / "logs"

def _get(name: str) -> str | None:
    """Return a stripped env value, or None if unset, blank or still a placeholder"""
    value = os.getenv(name, "").strip()
    if not value:
        return None
    placeholder = PLACEHOLDERS.get(name)
    if placeholder and placeholder in value:
        return None
    return value

def _get_float(name: str, low: float, high: float, errors: list[str]) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw)
    except ValueError:
        errors.append(f"{name} must be a number (got {raw!r})")
        return 0.0
    if not low <= value <= high:
        errors.append(f"{name} must be betwen {low} and {high} (got {value})")

    return value


@lru_cache(maxsize=1)
def get_settings(require_database: bool = True) -> Settings:
    """Build setting, raising one ConfigError that lists every problem found
    
    pass require_database=False until PostgreSQL is set up"""

    errors: list[str] = []

    api_key = _get("GARMIN_PERSONAL_API_KEY")
    if not api_key:
        errors.append("garmin personal api key is missing or still a placeholder")

    database_url = _get("DATABASE_URL")
    if require_database and not database_url:
        errors.append("datbase url is missing or still placeholder")

    latitude = _get_float("TRAINING_LATITUDE", -90, 90, errors)
    longitude = _get_float("TRAINING_LONGITUDE", -180, 180, errors)

    tz_name = os.getenv("TRAINING_TIMEZONE", "").strip()
    timezone = None

    try:
        timezone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append(f"training timezone must be an Iana name (got {tz_name})")

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in VALID_LOG_LEVELS:
        errors.append(f"log level must be one the {sorted(VALID_LOG_LEVELS)} (got{log_level})")

    if errors:
        details = "\n - ".join(errors)
        raise ConfigError(f" invalid config in {BASE_DIR / '.env'}:\n  - {details}")

    return Settings (
        garmin_api_key=api_key,
        database_url=database_url,
        latitude=latitude,
        longitide=longitude,
        timezone=timezone,
        log_level=log_level,
    )
