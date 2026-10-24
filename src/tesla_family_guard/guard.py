"""Pure family-guard decision logic — no network, no clock reads except the
sample's own timestamp, so every rule is unit-testable.

Rules (all from the queue spec):
- Speeding: a driving sample above the speed limit raises a safety alert.
- Curfew: driving inside the curfew window raises a safety alert (once per
  trip, via the cooldown).
- Geofence exit: a driving sample outside every configured geofence, after
  having been inside one, raises a non-safety alert — held during quiet
  hours until morning.
- Cooldowns: the same alert kind for the same car fires at most once per
  cooldown window, so one long drive doesn't spam the parent.
- Quiet hours: only safety alerts (speeding, curfew) go out at night;
  geofence alerts wait.

Weekly report card: aggregates samples into top speed, harsh-event count
(samples 20+ mph over the limit), night miles, total miles, curfew trips,
and geofence exits. Distance uses haversine between consecutive samples.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import parse_12h_time

EARTH_RADIUS_MILES = 3958.8
HARSH_OVER_MPH = 20
NIGHT_START_MIN = 22 * 60   # 10:00 PM
NIGHT_END_MIN = 5 * 60      # 5:00 AM


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2)
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _minutes_of(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def in_window(minutes: int, start_min: int, end_min: int) -> bool:
    """True if `minutes` falls in [start, end), wrapping past midnight."""
    if start_min <= end_min:
        return start_min <= minutes < end_min
    return minutes >= start_min or minutes < end_min


def in_curfew(dt: datetime, curfew_start: str, curfew_end: str) -> bool:
    return in_window(_minutes_of(dt), parse_12h_time(curfew_start),
                     parse_12h_time(curfew_end))


def in_quiet_hours(dt: datetime, quiet_start: str, quiet_end: str) -> bool:
    return in_window(_minutes_of(dt), parse_12h_time(quiet_start),
                     parse_12h_time(quiet_end))


def is_night(dt: datetime) -> bool:
    return in_window(_minutes_of(dt), NIGHT_START_MIN, NIGHT_END_MIN)


@dataclass
class DriveSample:
    vin: str
    vehicle_name: str
    at: datetime
    speed_mph: float
    latitude: float | None = None
    longitude: float | None = None
    driving: bool = True

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class Alert:
    kind: str              # "speeding" | "curfew" | "geofence_exit"
    vehicle_name: str
    at: datetime
    message: str
    safety: bool = True    # safety alerts ignore quiet hours
    deferred: bool = False  # held for quiet hours, not sent yet

    def plain(self) -> str:
        stamp = self.at.strftime("%a %I:%M %p")
        return f"{stamp} — {self.vehicle_name}: {self.message}"


@dataclass
class GuardState:
    """Per-car memory: last alert time per kind, and whether the car was
    last seen inside a geofence (so only real exits alert)."""
    last_alert: dict[tuple[str, str], datetime] = field(default_factory=dict)
    was_inside: dict[str, bool] = field(default_factory=dict)
    pending: list[Alert] = field(default_factory=list)  # quiet-hours holds


def _inside_any(sample: DriveSample, geofences: list) -> bool | None:
    """True/False if location is known and fences have coordinates;
    None if we cannot tell (no location, or no geocoded fence)."""
    if not sample.has_location:
        return None
    usable = [g for g in geofences
              if g.latitude is not None and g.longitude is not None]
    if not usable:
        return None
    return any(haversine_miles(sample.latitude, sample.longitude,
                               g.latitude, g.longitude) <= g.radius_miles
               for g in usable)


def evaluate_sample(sample: DriveSample, settings, state: GuardState) -> list[Alert]:
    """Decide which alerts (if any) a new sample raises. Parked samples
    only update geofence memory; they never alert."""
    out: list[Alert] = []
    if not sample.driving:
        inside = _inside_any(sample, settings.geofences)
        if inside is not None:
            state.was_inside[sample.vin] = inside
        return out

    def cooled(kind: str) -> bool:
        last = state.last_alert.get((sample.vin, kind))
        if last is None:
            return False
        elapsed = (sample.at - last).total_seconds() / 60.0
        return elapsed < settings.alert_cooldown_minutes

    def emit(kind: str, message: str, safety: bool) -> None:
        if cooled(kind):
            return
        alert = Alert(kind=kind, vehicle_name=sample.vehicle_name,
                      at=sample.at, message=message, safety=safety)
        if (not safety and in_quiet_hours(sample.at, settings.quiet_start,
                                          settings.quiet_end)):
            alert.deferred = True
            state.pending.append(alert)
        else:
            out.append(alert)
        state.last_alert[(sample.vin, kind)] = sample.at

    if sample.speed_mph > settings.speed_limit_mph:
        emit("speeding",
             f"Speeding at {sample.speed_mph:.0f} mph "
             f"(limit {settings.speed_limit_mph} mph).", safety=True)

    if in_curfew(sample.at, settings.curfew_start, settings.curfew_end):
        emit("curfew",
             f"Driving during curfew hours "
             f"({settings.curfew_start}–{settings.curfew_end}).", safety=True)

    inside = _inside_any(sample, settings.geofences)
    previously_inside = state.was_inside.get(sample.vin)
    if inside is False and previously_inside:
        emit("geofence_exit",
             "Left the allowed area while driving.", safety=False)
    if inside is not None:
        state.was_inside[sample.vin] = inside
    return out


def release_pending(state: GuardState, now: datetime,
                    quiet_start: str, quiet_end: str) -> list[Alert]:
    """Morning release: held non-safety alerts go out once quiet hours end."""
    if in_quiet_hours(now, quiet_start, quiet_end):
        return []
    due, state.pending = state.pending, []
    for alert in due:
        alert.deferred = False
    return due


# ---------------------------------------------------------------- weekly card

@dataclass
class WeekStats:
    vehicle_name: str
    total_miles: float = 0.0
    night_miles: float = 0.0
    top_speed_mph: float = 0.0
    speeding_samples: int = 0
    harsh_events: int = 0
    curfew_trips: int = 0
    geofence_exits: int = 0


def summarize_week(samples: list[DriveSample], alerts: list[Alert],
                   settings) -> dict[str, WeekStats]:
    """Aggregate samples + alerts per car. Samples must be chronological
    per car; miles come from consecutive-sample distances."""
    stats: dict[str, WeekStats] = {}
    prev: dict[str, DriveSample] = {}
    curfew_days: dict[str, set] = {}
    for s in samples:
        st = stats.setdefault(s.vehicle_name, WeekStats(vehicle_name=s.vehicle_name))
        if s.driving and s.speed_mph > st.top_speed_mph:
            st.top_speed_mph = s.speed_mph
        if s.driving and s.speed_mph > settings.speed_limit_mph:
            st.speeding_samples += 1
        if s.driving and s.speed_mph > settings.speed_limit_mph + HARSH_OVER_MPH:
            st.harsh_events += 1
        if s.driving and in_curfew(s.at, settings.curfew_start, settings.curfew_end):
            curfew_days.setdefault(s.vehicle_name, set()).add(s.at.date())
        p = prev.get(s.vin)
        if (p is not None and s.has_location and p.has_location
                and s.driving and p.driving):
            miles = haversine_miles(p.latitude, p.longitude,
                                    s.latitude, s.longitude)
            # Guard against teleporting samples (GPS jumps): ignore legs
            # longer than a car could cover between two samples.
            if miles < 50:
                st.total_miles += miles
                if is_night(s.at):
                    st.night_miles += miles
        prev[s.vin] = s
    for st in stats.values():
        st.curfew_trips = len(curfew_days.get(st.vehicle_name, set()))
    for a in alerts:
        st = stats.setdefault(a.vehicle_name, WeekStats(vehicle_name=a.vehicle_name))
        if a.kind == "geofence_exit":
            st.geofence_exits += 1
    return stats


def report_card_text(stats: WeekStats, settings) -> str:
    """Plain-English weekly report card for one car."""
    verdict = "Steady week — no red flags."
    if stats.harsh_events:
        verdict = ("Needs a conversation: harsh speeding happened "
                   f"{stats.harsh_events} time(s) this week.")
    elif stats.speeding_samples:
        verdict = "Mostly steady — a few moments over the limit to talk through."
    elif stats.curfew_trips:
        verdict = "Speed was fine, but there were late-night drives to ask about."
    return (
        f"Weekly report card — {stats.vehicle_name}\n"
        f"  Total miles: {stats.total_miles:.0f}  ·  Night miles: {stats.night_miles:.0f}\n"
        f"  Top speed: {stats.top_speed_mph:.0f} mph (limit {settings.speed_limit_mph} mph)\n"
        f"  Over-limit moments: {stats.speeding_samples}  ·  Harsh events (20+ over): {stats.harsh_events}\n"
        f"  Curfew nights: {stats.curfew_trips}  ·  Left the allowed area: {stats.geofence_exits} time(s)\n"
        f"  {verdict}"
    )


def week_brief(stats_map: dict[str, WeekStats], settings) -> str:
    """Compact text the LLM receives as context for report-card questions."""
    lines = []
    for name, st in sorted(stats_map.items()):
        lines.append(
            f"- {name}: {st.total_miles:.0f} miles ({st.night_miles:.0f} at night), "
            f"top speed {st.top_speed_mph:.0f} mph (limit {settings.speed_limit_mph}), "
            f"{st.speeding_samples} over-limit moments, {st.harsh_events} harsh events, "
            f"{st.curfew_trips} curfew nights, {st.geofence_exits} geofence exits.")
    return "\n".join(lines) or "(no driving data this week)"


# ------------------------------------------------------------------ ntfy alerts

def send_ntfy_alert(topic: str, alert: Alert, timeout: float = 10.0) -> bool:
    """Post one alert to the parent's ntfy.sh topic. Returns False (never
    raises) when the topic is blank or the post fails — the caller reports
    the failure in plain words instead of crashing."""
    if not topic:
        return False
    try:
        import requests
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=alert.plain().encode(),
            headers={"Title": f"Tesla Family Guard: {alert.kind.replace('_', ' ')}",
                     "Priority": "urgent" if alert.safety else "default"},
            timeout=timeout)
        return resp.status_code < 300
    except Exception:
        return False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
