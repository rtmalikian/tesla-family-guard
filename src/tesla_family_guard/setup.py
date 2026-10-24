"""Guided first-run setup: plain-language questions, writes .env itself.

Built for Tesla owners, not developers — defaults everywhere, numbered
choices, places by name + street address (the app geocodes the address,
so nobody ever types coordinates), times in 12-hour words. Testable:
input and output are injectable.
"""
from __future__ import annotations

import os
from pathlib import Path


def _ask(input_fn, out, prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    out(f"{prompt}{suffix}")
    answer = input_fn("> ").strip()
    return answer or default


def _ask_required(input_fn, out, prompt: str, help_text: str) -> str:
    while True:
        out(help_text)
        answer = input_fn(f"{prompt} ").strip()
        if answer:
            return answer
        out("That one's required — without it the app can't do its job.")


def _geocode(address: str):
    """Best-effort free geocode (OpenStreetMap Nominatim). Returns
    (lat, lon) or None — failure just means geofence checks wait until
    setup runs again with a connection; it never blocks setup."""
    try:
        import requests
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "tesla-family-guard/0.1 (setup wizard)"},
            timeout=8)
        rows = resp.json()
        if rows:
            return float(rows[0]["lat"]), float(rows[0]["lon"])
    except Exception:
        pass
    return None


def run_setup(input_fn=input, out=print, env_path: str = ".env") -> Path:
    out("")
    out("Welcome to Tesla Family Guard setup — I'll ask a few questions and")
    out("write the settings file for you. Press Enter to accept a [default].")
    out("")

    path = Path(env_path)
    if path.exists():
        again = _ask(input_fn, out,
                     "A settings file (.env) already exists. Replace it? (y/n)", "n")
        if again.lower() not in ("y", "yes"):
            out("Keeping your existing settings. Nothing changed.")
            return path

    out("STEP 1 of 5 — Connect to Tesla")
    out("Create a free developer app at developer.tesla.com (sign in, then")
    out("'Create App'). Tesla will show you a Client ID and Client Secret.")
    client_id = _ask_required(input_fn, out, "Paste your Client ID:",
                              "First, the Client ID:")
    client_secret = _ask_required(input_fn, out, "Paste your Client Secret:",
                                  "Now the Client Secret (it stays on this computer):")

    out("")
    out("STEP 2 of 5 — Your cars")
    out("For each car: a nickname and its VIN. Find the VIN in your Tesla")
    out("app under Controls → Software (or on the car's touchscreen).")
    vehicles: list[tuple[str, str]] = []
    while True:
        n = len(vehicles) + 1
        name = _ask(input_fn, out,
                    f"Car {n} nickname (e.g. Model Y) — or press Enter if done:",
                    "" if vehicles else "")
        if not name:
            if vehicles:
                break
            out("Add at least one car to continue.")
            continue
        vin = _ask_required(input_fn, out, f"VIN for {name}:",
                            f"Now the VIN for {name}:")
        vehicles.append((name, vin))

    out("")
    out("STEP 3 of 5 — The ground rules")
    out("These are the rules every driver in the family is measured against.")
    speed = _ask(input_fn, out,
                 "Speed that counts as speeding (miles per hour):", "75")
    curfew_start = _ask(input_fn, out,
                        "Curfew starts at (like 11:00 PM):", "11:00 PM")
    curfew_end = _ask(input_fn, out,
                      "Curfew ends at (like 5:00 AM):", "5:00 AM")
    quiet_start = _ask(input_fn, out,
                       "Quiet hours start at (non-urgent alerts wait):", "10:00 PM")
    quiet_end = _ask(input_fn, out,
                     "Quiet hours end at (like 7:00 AM):", "7:00 AM")
    cooldown = _ask(input_fn, out,
                    "Minutes between repeat alerts for the same thing:", "60")

    out("")
    out("STEP 4 of 5 — Where home is, and how alerts reach you")
    out("Name the place, then its street address — I'll look up its map")
    out("position for you, so you never type coordinates.")
    place = _ask(input_fn, out, "Allowed-area name (e.g. Home):", "Home")
    address = _ask(input_fn, out,
                   "Street address for that place:", "38556 31st St E, Palmdale, CA 93550")
    radius = _ask(input_fn, out,
                  "How many miles around it count as 'in the area'?", "5")
    out("Looking up that address…")
    coords = _geocode(address) if address else None
    if coords:
        out(f"Found it: {coords[0]:.4f}, {coords[1]:.4f}.")
        fence = f"{place}|{address}|{coords[0]:.5f},{coords[1]:.5f},{radius}"
    else:
        out("Couldn't look it up just now (no connection?) — I'll save the")
        out("address, and geofence alerts will start once you re-run setup")
        out("with a connection. Speeding and curfew alerts work regardless.")
        fence = f"{place}|{address}||{radius}"
    out("")
    out("Alerts go to your phone through ntfy.sh (free): install the ntfy")
    out("app, pick a topic name only you would guess, and subscribe to it.")
    topic = _ask(input_fn, out,
                 "Your ntfy topic name (blank = alerts only on screen):", "")

    out("")
    out("STEP 5 of 5 — The AI brain (optional) and the report server")
    out("  1) Built-in answers only — no AI, nothing leaves this computer")
    out("  2) Ollama on this computer — free local AI (default)")
    out("  3) Another AI service (OpenAI, Groq, LM Studio…) — you'll paste its details")
    choice = _ask(input_fn, out, "Pick 1, 2 or 3:", "2")
    ai_mode, ai_url, ai_key, ai_model = "auto", "http://localhost:11434/v1", "", "llama3.1"
    if choice == "1":
        ai_mode = "never"
    elif choice == "3":
        ai_url = _ask_required(input_fn, out, "Service address (base URL):",
                               "Paste the service's API address:")
        ai_key = _ask(input_fn, out, "API key for that service (stored only here):")
        ai_model = _ask(input_fn, out, "Model name:", "gpt-4o-mini")
    port = _ask(input_fn, out, "Port for the report address:", "8647")
    server_key = _ask(input_fn, out,
                      "Optional password for the report address (blank = none):")

    lines = [
        "# Written by `tfguard setup` — edit by re-running setup any time.",
        f"TESLA_CLIENT_ID={client_id}",
        f"TESLA_CLIENT_SECRET={client_secret}",
        "TESLA_REGION=na",
        "TESLA_REDIRECT_URI=http://localhost:8080/callback",
        "TFG_VEHICLES=" + ",".join(f"{name}={vin}" for name, vin in vehicles),
        "TFG_SERVER_HOST=127.0.0.1",
        f"TFG_SERVER_PORT={port}",
        f"TFG_SERVER_API_KEY={server_key}",
        "TFG_MODEL_ID=tesla-family-guard",
        f"TFG_AI_BASE_URL={ai_url}",
        f"TFG_AI_API_KEY={ai_key}",
        f"TFG_AI_MODEL={ai_model}",
        f"TFG_AI_MODE={ai_mode}",
        "TFG_AI_TIMEOUT_SECONDS=20",
        "TFG_EMBEDDING_DIM=384",
        "TFG_TOKEN_FILE=~/.tfg/tokens.json",
        f"TFG_SPEED_LIMIT_MPH={speed}",
        f"TFG_CURFEW_START={curfew_start}",
        f"TFG_CURFEW_END={curfew_end}",
        f"TFG_QUIET_START={quiet_start}",
        f"TFG_QUIET_END={quiet_end}",
        f"TFG_ALERT_COOLDOWN_MINUTES={cooldown}",
        f"TFG_NTFY_TOPIC={topic}",
        f"TFG_GEOFENCES={fence}",
        "TFG_DATA_FILE=~/.tfg/drives.jsonl",
        "TFG_DRY_RUN=0",
    ]
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)

    out("")
    out("All set — settings saved to .env (only readable by you).")
    out("Next steps:")
    out("  1) tfguard auth       — sign in to Tesla once (opens a link)")
    out("  2) tfguard simulate   — see a demo week with pretend cars")
    out("  3) tfguard monitor    — preview this week's alerts (dry-run first)")
    out("  4) tfguard serve      — start the weekly report-card API")
    return path
