"""End-to-end: the demo week asserts the core invariant — a speeding
alert, a curfew alert, and a report card whose top speed is 98 mph."""
from tesla_family_guard.config import Settings
from tesla_family_guard.guard import report_card_text
from tesla_family_guard.simulator import (demo_fences, run_demo_week,
                                          timeline_lines)


def _settings():
    s = Settings()
    s.geofences = demo_fences()
    return s


def test_demo_week_invariant():
    samples, alerts, stats = run_demo_week(_settings())
    kinds = {a.kind for a in alerts}
    assert "speeding" in kinds
    assert "curfew" in kinds
    assert "geofence_exit" in kinds
    # Cooldown: three 98 mph samples in a row -> exactly one speeding alert.
    assert sum(1 for a in alerts if a.kind == "speeding") == 1
    st = stats["Model Y"]
    assert st.top_speed_mph == 98
    assert st.harsh_events == 3  # all three 98 mph samples are harsh moments
    assert st.curfew_trips == 2  # Fri 1:30 AM + Sat 11:15 PM
    assert st.geofence_exits >= 1
    card = report_card_text(st, _settings())
    assert "98 mph" in card


def test_simulate_timeline_renders():
    lines = timeline_lines(_settings())
    blob = "\n".join(lines)
    assert "ALERT" in blob
    assert "Weekly report card" in blob
    assert "Fleet API cost" in blob
