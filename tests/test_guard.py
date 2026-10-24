"""Decision-logic unit tests, including edge cases."""
from datetime import datetime, timezone

import pytest

from tesla_family_guard.config import Settings
from tesla_family_guard.guard import (DriveSample, GuardState, evaluate_sample,
                                      haversine_miles, in_curfew,
                                      in_quiet_hours, is_night,
                                      release_pending, summarize_week)

HOME = (34.5793, -118.1165)
FAR = (34.0500, -118.2500)


def _settings(**kw):
    s = Settings()
    s.geofences = []
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _sample(speed=50, hour=12, minute=0, lat=None, lon=None, driving=True):
    return DriveSample("VIN1", "Model Y",
                       datetime(2026, 10, 20, hour, minute, tzinfo=timezone.utc),
                       speed, lat, lon, driving)


def _fenced_settings():
    from tesla_family_guard.config import Geofence
    s = _settings()
    s.geofences = [Geofence("Home", "Palmdale, CA", HOME[0], HOME[1], 5.0)]
    return s


def test_speeding_alert_and_exactly_at_limit_is_fine():
    st = GuardState()
    assert evaluate_sample(_sample(76), _settings(), st)[0].kind == "speeding"
    st = GuardState()
    assert evaluate_sample(_sample(75), _settings(), st) == []


def test_cooldown_swallows_repeats_then_refires():
    s = _settings(alert_cooldown_minutes=60)
    st = GuardState()
    assert len(evaluate_sample(_sample(90, 12, 0), s, st)) == 1
    assert evaluate_sample(_sample(90, 12, 30), s, st) == []
    assert len(evaluate_sample(_sample(90, 13, 1), s, st)) == 1


def test_curfew_wraps_midnight():
    assert in_curfew(_sample(40, 0, 30).at, "11:00 PM", "5:00 AM")
    assert in_curfew(_sample(40, 23, 30).at, "11:00 PM", "5:00 AM")
    assert not in_curfew(_sample(40, 6, 0).at, "11:00 PM", "5:00 AM")
    assert not in_curfew(_sample(40, 10, 59).at, "11:00 PM", "5:00 AM")
    st = GuardState()
    alerts = evaluate_sample(_sample(40, 1, 30), _settings(), st)
    assert [a.kind for a in alerts] == ["curfew"]


def test_quiet_hours_hold_non_safety_alerts_only():
    s = _fenced_settings()
    st = GuardState()
    # Parked at home first, so the car is known-inside.
    evaluate_sample(_sample(0, 22, 0, *HOME, driving=False), s, st)
    got = evaluate_sample(_sample(40, 23, 30, *FAR), s, st)
    # 11:30 PM is also curfew: the safety alert fires, the geofence one holds.
    assert [a.kind for a in got] == ["curfew"]
    assert len(st.pending) == 1 and st.pending[0].kind == "geofence_exit"
    # ...but a speeding sample at the same hour still alerts immediately.
    assert evaluate_sample(_sample(90, 23, 35, *FAR), s, st)[0].safety
    released = release_pending(st, _sample(0, 7, 5).at, s.quiet_start, s.quiet_end)
    assert len(released) == 1 and released[0].kind == "geofence_exit"
    assert not released[0].deferred


def test_geofence_exit_needs_prior_inside():
    s = _fenced_settings()
    st = GuardState()
    # First-ever sample already far away: no exit alert (never seen inside).
    assert evaluate_sample(_sample(40, 12, 0, *FAR), s, st) == []
    evaluate_sample(_sample(40, 12, 10, *HOME), s, st)
    alerts = evaluate_sample(_sample(40, 12, 20, *FAR), s, st)
    assert [a.kind for a in alerts] == ["geofence_exit"]


def test_no_location_never_alerts_geofence():
    s = _fenced_settings()
    st = GuardState()
    evaluate_sample(_sample(40, 12, 0, *HOME), s, st)
    assert evaluate_sample(_sample(40, 12, 10), s, st) == []


def test_parked_samples_never_alert():
    st = GuardState()
    assert evaluate_sample(_sample(90, 1, 30, driving=False), _settings(), st) == []


def test_haversine_and_night():
    assert haversine_miles(*HOME, *HOME) == pytest.approx(0.0)
    assert haversine_miles(*HOME, *FAR) > 30
    assert is_night(_sample(0, 23, 0).at)
    assert not is_night(_sample(0, 12, 0).at)


def test_week_summary_counts():
    s = _settings()
    samples = [_sample(50, 8, 0, *HOME), _sample(100, 8, 10, *HOME),
               _sample(60, 23, 0, *HOME)]
    stats = summarize_week(samples, [], s)
    st = stats["Model Y"]
    assert st.top_speed_mph == 100
    assert st.speeding_samples == 1
    assert st.harsh_events == 1  # 100 > 75 + 20
    assert st.night_miles == pytest.approx(0.0)  # same spot, no distance


def test_quiet_window_wraps_midnight():
    assert in_quiet_hours(_sample(0, 23, 30).at, "10:00 PM", "7:00 AM")
    assert in_quiet_hours(_sample(0, 6, 59).at, "10:00 PM", "7:00 AM")
    assert not in_quiet_hours(_sample(0, 12, 0).at, "10:00 PM", "7:00 AM")
