"""Live fleet snapshot: no-wake reads of each configured vehicle, distilled
into a compact state object the rules engine, LLM context builder, and
command executor share."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VehicleState:
    name: str
    vin: str
    display_name: str = ""
    battery_level: int = 0
    charging_state: str = "Disconnected"   # Charging | Stopped | Complete | Disconnected
    inside_temp_c: float | None = None
    outside_temp_c: float | None = None
    is_climate_on: bool = False
    sentry_mode: bool = False
    locked: bool = True
    odometer: float = 0.0
    shift_state: str | None = None          # P | D | R | N
    reachable: bool = True
    error: str = ""


@dataclass
class FleetSnapshot:
    vehicles: list[VehicleState] = field(default_factory=list)

    def brief(self) -> str:
        """Compact text the LLM receives as context ('fleet brief')."""
        lines = []
        for v in self.vehicles:
            if not v.reachable:
                lines.append(f"- {v.name}: unreachable ({v.error})")
                continue
            lines.append(
                f"- {v.name}: battery {v.battery_level}%, charging state {v.charging_state}, "
                f"climate {'on' if v.is_climate_on else 'off'}, "
                f"inside {v.inside_temp_c}°C / outside {v.outside_temp_c}°C, "
                f"sentry {'on' if v.sentry_mode else 'off'}, "
                f"{'locked' if v.locked else 'unlocked'}, "
                f"odometer {v.odometer:.0f} mi, gear {v.shift_state or 'unknown'}"
            )
        return "\n".join(lines) or "(no vehicles)"


def _climate(d: dict) -> dict:
    return d.get("climate_state") or {}


def _drive(d: dict) -> dict:
    return d.get("drive_state") or {}


def _charge(d: dict) -> dict:
    return d.get("charge_state") or {}


def snapshot_fleet(client, vehicles: list) -> FleetSnapshot:
    """Read every configured vehicle (no-wake reads only) and build a snapshot."""
    snap = FleetSnapshot()
    for vc in vehicles:
        try:
            data = client.vehicle_data(vc.vin)
        except Exception as exc:  # never let one car break the whole fleet view
            snap.vehicles.append(VehicleState(name=vc.name, vin=vc.vin,
                                              reachable=False, error=str(exc)[:120]))
            continue
        cs, cl, dr = _charge(data), _climate(data), _drive(data)
        snap.vehicles.append(VehicleState(
            name=vc.name,
            vin=vc.vin,
            display_name=str(data.get("display_name") or ""),
            battery_level=int(cs.get("battery_level") or 0),
            charging_state=str(cs.get("charging_state") or "Disconnected"),
            inside_temp_c=cl.get("inside_temp"),
            outside_temp_c=cl.get("outside_temp"),
            is_climate_on=bool(cl.get("is_climate_on")),
            sentry_mode=bool(data.get("sentry_mode")),
            locked=bool(data.get("locked", True)),
            odometer=float(dr.get("odometer") or 0.0),
            shift_state=dr.get("shift_state"),
        ))
    return snap


def find_vehicle(snap: FleetSnapshot, mention: str) -> VehicleState | None:
    """Best-effort vehicle resolution from a free-text mention."""
    needle = mention.strip().lower()
    if not needle:
        return None
    for v in snap.vehicles:
        names = [v.name.lower()] + ([v.display_name.lower()] if v.display_name else [])
        for nm in names:
            if nm and (needle in nm or nm in needle):
                return v
    for v in snap.vehicles:
        for m in ("model 3", "model y", "model s", "model x"):
            if m in needle and m[-1] in v.name.lower():
                return v
    return None
