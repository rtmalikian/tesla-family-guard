import pytest

from tesla_family_guard.config import (ConfigError, format_12h_time,
                                       load_settings, parse_12h_time)

BASE = {"TFG_VEHICLES": "Model Y=VINY,Model 3=VIN3"}


def test_defaults():
    s = load_settings(BASE)
    assert s.server_port == 8647
    assert s.model_id == "tesla-family-guard"
    assert s.speed_limit_mph == 75
    assert s.curfew_start == "11:00 PM"
    assert s.alert_cooldown_minutes == 60
    assert len(s.vehicles) == 2
    assert s.vehicles[0].name == "Model Y"


def test_12h_parsing_and_roundtrip():
    assert parse_12h_time("11:00 PM") == 23 * 60
    assert parse_12h_time("12:00 AM") == 0
    assert parse_12h_time("12:00 PM") == 12 * 60
    assert parse_12h_time("5:05 am") == 5 * 60 + 5
    assert format_12h_time(23 * 60) == "11:00 PM"
    assert format_12h_time(0) == "12:00 AM"


def test_bad_times_rejected_with_human_message():
    with pytest.raises(ConfigError, match="11:00 PM"):
        load_settings({**BASE, "TFG_CURFEW_START": "23:00"})
    with pytest.raises(ConfigError, match="13:00 PM"):
        load_settings({**BASE, "TFG_QUIET_END": "13:00 PM"})
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TFG_AI_MODE": "sometimes"})


def test_geofences_and_overrides():
    s = load_settings({**BASE,
                       "TFG_SPEED_LIMIT_MPH": "65",
                       "TFG_GEOFENCES": "Home|Palmdale, CA|34.5793,-118.1165,5"})
    assert s.speed_limit_mph == 65
    assert len(s.geofences) == 1
    assert s.geofences[0].name == "Home"
    assert s.geofences[0].latitude == pytest.approx(34.5793)
    assert s.geofences[0].radius_miles == 5.0


def test_address_only_geofence_loads():
    s = load_settings({**BASE, "TFG_GEOFENCES": "Home|Palmdale, CA||5"})
    assert s.geofences[0].latitude is None
    assert s.geofences[0].radius_miles == 5.0


def test_bad_region_and_speed():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TESLA_REGION": "xx"})
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TFG_SPEED_LIMIT_MPH": "0"})
    with pytest.raises(ConfigError):
        load_settings({"TFG_VEHICLES": "Model Y="})
