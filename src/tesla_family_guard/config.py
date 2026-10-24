"""Configuration for Tesla Family Guard. All settings come from the
environment (see .env.example). Copy .env.example to .env — .env is
git-ignored so secrets never leave your machine.

Times are written the way owners say them ("11:00 PM"), never as
24-hour numbers. Places are named ("Home") with a street address; the
setup wizard geocodes the address so nobody ever types coordinates.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


class ConfigError(Exception):
    pass


@dataclass
class VehicleConfig:
    name: str
    vin: str


@dataclass
class Geofence:
    name: str
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    radius_miles: float = 5.0


@dataclass
class Settings:
    client_id: str = ""
    client_secret: str = ""
    region: str = "na"
    redirect_uri: str = "http://localhost:8080/callback"
    token_file: str = "~/.tfg/tokens.json"
    vehicles: list[VehicleConfig] = field(default_factory=list)
    # The OpenAI-compatible server this app exposes.
    server_host: str = "127.0.0.1"
    server_port: int = 8647
    server_api_key: str = ""          # optional bearer token for /v1/*
    model_id: str = "tesla-family-guard"
    # Pluggable LLM backend (any OpenAI-compatible API; default: local Ollama).
    ai_base_url: str = "http://localhost:11434/v1"
    ai_api_key: str = ""
    ai_model: str = "llama3.1"
    ai_mode: str = "auto"             # auto | always | never
    ai_timeout_seconds: float = 20.0
    embedding_dim: int = 384
    dry_run: bool = False
    # Family-guard rules (defaults are the common, safe answers).
    speed_limit_mph: int = 75
    curfew_start: str = "11:00 PM"    # driving during curfew alerts
    curfew_end: str = "5:00 AM"
    quiet_start: str = "10:00 PM"     # non-safety alerts wait until morning
    quiet_end: str = "7:00 AM"
    alert_cooldown_minutes: int = 60
    ntfy_topic: str = ""              # parent's ntfy.sh topic; blank = no alerts sent
    geofences: list[Geofence] = field(default_factory=list)
    data_file: str = "~/.tfg/drives.jsonl"


def _parse_vehicles(raw: str) -> list[VehicleConfig]:
    """Format: name=VIN,name2=VIN2 (or bare VINs)."""
    vehicles = []
    for idx, item in enumerate(raw.split(",")):
        item = item.strip()
        if not item:
            continue
        name = None
        if "=" in item:
            name, item = item.split("=", 1)
            name = name.strip()
        vin = item.strip()
        if not vin:
            raise ConfigError("Empty VIN in TFG_VEHICLES")
        vehicles.append(VehicleConfig(name=name or f"car-{idx + 1}", vin=vin))
    if not vehicles:
        raise ConfigError("TFG_VEHICLES is empty — add at least one name=VIN entry")
    return vehicles


def parse_12h_time(raw: str) -> int:
    """'11:00 PM' -> minutes after midnight. Raises ConfigError on bad input."""
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*([APap][Mm])\s*$", raw or "")
    if not m:
        raise ConfigError(
            f"Time must look like '11:00 PM', got {raw!r}. "
            "Write the hour, a colon, the minutes, and AM or PM.")
    hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        raise ConfigError(f"Not a real clock time: {raw!r}")
    if meridiem == "PM" and hour != 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0
    return hour * 60 + minute


def format_12h_time(minutes: int) -> str:
    minutes %= 24 * 60
    hour, minute = divmod(minutes, 60)
    meridiem = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {meridiem}"


def _parse_geofences(raw: str) -> list[Geofence]:
    """Format: name|address|lat,lon,radius_miles; one per ';'.
    Lat/lon may be empty (address-only fence: geofence checks skip it
    until setup geocodes it)."""
    fences = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split("|")]
        name = parts[0]
        address = parts[1] if len(parts) > 1 else ""
        lat = lon = None
        radius = 5.0
        if len(parts) > 2 and parts[2]:
            try:
                lat_s, lon_s, *rest = parts[2].split(",")
                lat, lon = float(lat_s), float(lon_s)
                if rest:
                    radius = float(rest[0])
            except ValueError as exc:
                raise ConfigError(f"Bad geofence coordinates in {item!r}") from exc
        elif len(parts) > 3 and parts[3]:
            # Address-only fence (geocode pending): radius in 4th field.
            try:
                radius = float(parts[3])
            except ValueError as exc:
                raise ConfigError(f"Bad geofence radius in {item!r}") from exc
        fences.append(Geofence(name=name, address=address,
                               latitude=lat, longitude=lon, radius_miles=radius))
    return fences


def _int(env: dict, key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{key} must be a whole number, got {raw!r}") from exc


def _float(env: dict, key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _bool(env: dict, key: str, default: bool = False) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_settings(env: dict | None = None) -> Settings:
    env = os.environ if env is None else env
    s = Settings()
    s.client_id = env.get("TESLA_CLIENT_ID", "")
    s.client_secret = env.get("TESLA_CLIENT_SECRET", "")
    s.region = env.get("TESLA_REGION", "na").strip().lower()
    if s.region not in ("na", "eu", "cn"):
        raise ConfigError(f"TESLA_REGION must be na|eu|cn, got {s.region!r}")
    s.redirect_uri = env.get("TESLA_REDIRECT_URI", s.redirect_uri)
    s.token_file = env.get("TFG_TOKEN_FILE", s.token_file)
    raw_vehicles = env.get("TFG_VEHICLES", "")
    if raw_vehicles.strip():
        s.vehicles = _parse_vehicles(raw_vehicles)
    s.server_host = env.get("TFG_SERVER_HOST", s.server_host)
    s.server_port = _int(env, "TFG_SERVER_PORT", s.server_port)
    s.server_api_key = env.get("TFG_SERVER_API_KEY", "")
    s.model_id = env.get("TFG_MODEL_ID", s.model_id)
    s.ai_base_url = env.get("TFG_AI_BASE_URL", s.ai_base_url).rstrip("/")
    s.ai_api_key = env.get("TFG_AI_API_KEY", "")
    s.ai_model = env.get("TFG_AI_MODEL", s.ai_model)
    s.ai_mode = env.get("TFG_AI_MODE", s.ai_mode).strip().lower()
    if s.ai_mode not in ("auto", "always", "never"):
        raise ConfigError(f"TFG_AI_MODE must be auto|always|never, got {s.ai_mode!r}")
    s.ai_timeout_seconds = _float(env, "TFG_AI_TIMEOUT_SECONDS", s.ai_timeout_seconds)
    s.embedding_dim = _int(env, "TFG_EMBEDDING_DIM", s.embedding_dim)
    if not (8 <= s.embedding_dim <= 4096):
        raise ConfigError("TFG_EMBEDDING_DIM must be between 8 and 4096")
    s.dry_run = _bool(env, "TFG_DRY_RUN")
    s.speed_limit_mph = _int(env, "TFG_SPEED_LIMIT_MPH", s.speed_limit_mph)
    if s.speed_limit_mph <= 0:
        raise ConfigError("TFG_SPEED_LIMIT_MPH must be above 0")
    s.curfew_start = env.get("TFG_CURFEW_START", s.curfew_start)
    s.curfew_end = env.get("TFG_CURFEW_END", s.curfew_end)
    s.quiet_start = env.get("TFG_QUIET_START", s.quiet_start)
    s.quiet_end = env.get("TFG_QUIET_END", s.quiet_end)
    # Validate all four times up front so a typo fails fast, with a human message.
    for label, raw in (("curfew start", s.curfew_start), ("curfew end", s.curfew_end),
                       ("quiet start", s.quiet_start), ("quiet end", s.quiet_end)):
        try:
            parse_12h_time(raw)
        except ConfigError as exc:
            raise ConfigError(f"TFG {label} time is wrong: {exc}") from exc
    s.alert_cooldown_minutes = _int(env, "TFG_ALERT_COOLDOWN_MINUTES",
                                    s.alert_cooldown_minutes)
    s.ntfy_topic = env.get("TFG_NTFY_TOPIC", "")
    s.geofences = _parse_geofences(env.get("TFG_GEOFENCES", ""))
    s.data_file = env.get("TFG_DATA_FILE", s.data_file)
    return s
