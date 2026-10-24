"""Simulated driving week for tests, demos, and the GitHub Pages POC.
No API calls, no real cars. One pretend car, one week of drives:

- Mon: steady commute, all inside the limit and the allowed area.
- Wed evening: a 98 mph stretch (speeding + harsh event) — alerts once,
  then the cooldown swallows the repeats.
- Fri night: driving at 1:30 AM (curfew) and out past the allowed area.
- Sat: quiet-hours geofence exit, held until morning and released.

Core invariant the e2e test asserts: the week ends with a speeding
alert, a curfew alert, and a report card whose top speed is 98 mph.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import Geofence
from .guard import (Alert, DriveSample, GuardState, evaluate_sample,
                    release_pending, summarize_week)

HOME = (34.5793, -118.1165)  # Palmdale, CA (pretend home base)
FAR = (34.0500, -118.2500)   # downtown LA — well outside a 5-mile fence


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    # Week of Mon 2026-10-19 (hours used as-is by the rules).
    return datetime(2026, 10, 19 + day, hour, minute, tzinfo=timezone.utc)


def demo_fences() -> list[Geofence]:
    return [Geofence(name="Home", address="Palmdale, CA",
                     latitude=HOME[0], longitude=HOME[1], radius_miles=5.0)]


def demo_samples() -> list[DriveSample]:
    vin, name = "DEMO-VIN-1", "Model Y"
    samples: list[DriveSample] = []
    # Mon commute: 45 -> 55 -> 50 mph, drifting a few hundred metres.
    for i, speed in enumerate((45, 55, 50)):
        samples.append(DriveSample(vin, name, _at(0, 8, i * 10), speed,
                                   HOME[0] + i * 0.002, HOME[1] + i * 0.002))
    # Wed evening: 98 mph three times in a row (cooldown -> one alert).
    for i in range(3):
        samples.append(DriveSample(vin, name, _at(2, 18, i * 5), 98,
                                   HOME[0] + 0.01 * i, HOME[1] + 0.01 * i))
    # Fri night: curfew drive at 1:30 AM, ending far from home.
    samples.append(DriveSample(vin, name, _at(4, 1, 30), 40, *HOME))
    samples.append(DriveSample(vin, name, _at(4, 1, 45), 48, *FAR))
    # Sat night: geofence exit at 11:30 PM (quiet hours -> held).
    samples.append(DriveSample(vin, name, _at(5, 23, 15), 35, *HOME))
    samples.append(DriveSample(vin, name, _at(5, 23, 30), 38, *FAR))
    samples.append(DriveSample(vin, name, _at(5, 23, 45), 36, *FAR))
    return samples


def run_demo_week(settings) -> tuple[list[DriveSample], list[Alert], dict]:
    """Feed the demo week through the rules engine. Returns
    (samples, all alerts including morning-released holds, week stats)."""
    state = GuardState()
    alerts: list[Alert] = []
    for s in demo_samples():
        alerts.extend(evaluate_sample(s, settings, state))
    # Sunday 7:05 AM: quiet hours over -> held alerts release.
    alerts.extend(release_pending(state, _at(6, 7, 5),
                                  settings.quiet_start, settings.quiet_end))
    stats = summarize_week(demo_samples(), alerts, settings)
    return demo_samples(), alerts, stats


def timeline_lines(settings) -> list[str]:
    """Human-readable demo timeline for `tfguard simulate`."""
    samples, alerts, stats = run_demo_week(settings)
    by_time = {a.at: a for a in alerts}
    lines = ["Tesla Family Guard — demo week (pretend car, pretend drives)"]
    for s in samples:
        line = (f"{s.at.strftime('%a %I:%M %p')} — {s.vehicle_name} driving "
                f"at {s.speed_mph:.0f} mph")
        alert = by_time.get(s.at)
        if alert:
            held = " (held for quiet hours, released Sunday morning)" \
                if alert.kind == "geofence_exit" else ""
            line += f"  → ALERT: {alert.message}{held}"
        lines.append(line)
    lines.append("")
    for st in stats.values():
        from .guard import report_card_text
        lines.append(report_card_text(st, settings))
    data_calls = len(samples)
    lines.append("")
    lines.append("Expected Fleet API cost: this app only reads while the car")
    lines.append(f"is already awake (driving). {data_calls} no-wake reads in")
    lines.append("the demo week ≈ $0.03/week at community-reported rates;")
    lines.append("wakes are never issued to measure anything, so the real")
    lines.append("bill stays near zero. Alerts go out free via ntfy.sh.")
    return lines
