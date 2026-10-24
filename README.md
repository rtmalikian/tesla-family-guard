# Tesla Family Guard — Teen Driver Alerts + Weekly Report Cards for Your Tesla (Free, Open Source)

**Free, open-source Ford MyKey-style safety monitor for family Teslas.** Tesla's Speed Limit Mode caps speed but never tells you anything — no alert when your teen speeds, no word when the car leaves town at 1 AM, no report at the end of the week. **Tesla Family Guard** watches while the car is already awake (driving), alerts you on speeding, curfew driving, and geofence exits via free ntfy.sh phone alerts, and writes a plain-English **weekly report card** per car — top speed, harsh events, night miles, curfew nights — answerable through its own **OpenAI-compatible API**.

Works with Model 3, Model Y, Model S, Model X, and Cybertruck.

▶ **[Try the live demo](https://rtmalikian.github.io/tesla-family-guard/)** — run a pretend driving week in your browser, no install, no car needed.

## Why?

Parents hand a 400-horsepower computer to a new driver and get… silence. Owners ask constantly: *"how do I know if my kid is speeding in the Tesla?"*, *"can Tesla alert me when my teen leaves town?"*, *"is there a teen driver report for Tesla?"* The answers today are paid apps, OBD dongles, or nothing. Tesla already knows speed and location exactly — this turns that into answers:

- **Speeding alerts** — a sample over your limit (default 75 mph) pings your phone, once per hour per car (cooldown), not once per second
- **Curfew alerts** — driving between your curfew hours (default 11:00 PM–5:00 AM) alerts immediately, even at night
- **Geofence exits** — the car leaving your allowed area alerts you; non-urgent at night, so it waits quietly until morning (quiet hours, default 10:00 PM–7:00 AM)
- **Weekly report card** — per car: total miles, night miles, top speed, over-limit moments, harsh events (20+ mph over), curfew nights, area exits — plus a one-line verdict
- **AI report explanations** — ask the OpenAI-compatible endpoint *"was anyone speeding this week?"* and get the card; connect any OpenAI-compatible LLM backend (local Ollama by default) and it explains the week in free-form words
- **Watch-only, by design** — this app never commands a car. It cannot lock, unlock, charge, or limit anything. It watches, alerts, and reports.

## How it works

```
Mon 8:00 AM   Model Y drives to school at 50 mph ......... all good, no alert
Wed 6:00 PM   Model Y hits 98 mph ....................... → ALERT: speeding (once; cooldown swallows repeats)
Fri 1:30 AM   Model Y driving during curfew ............. → ALERT: curfew driving
Fri 1:45 AM   Model Y leaves the allowed area ........... → ALERT held for quiet hours
Sun 7:05 AM   Quiet hours end ........................... → held alert released to your phone
Sunday        Weekly report card: top speed 98 mph, 3 harsh moments, 2 curfew nights
```

**Expected API cost:** this app only reads while the car is already awake (driving) — it never wakes a car to measure anything. A typical week costs ~$0.03 in Fleet API reads at community-reported rates; alerts go out free via ntfy.sh.

## Quick start

```bash
git clone https://github.com/rtmalikian/tesla-family-guard && cd tesla-family-guard
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/tfguard setup    # guided setup — plain-language questions, writes .env for you
.venv/bin/tfguard auth     # one-time Tesla authorization + virtual-key pairing
.venv/bin/tfguard simulate # demo week with a pretend car — no car, no keys
.venv/bin/tfguard monitor  # dry-run preview of this week's alerts (sends nothing)
.venv/bin/tfguard monitor --live  # after the preview: confirm, then send for real
.venv/bin/tfguard serve    # start the OpenAI-compatible report-card API
# or one-shot, no server:
.venv/bin/tfguard ask "weekly report for the Model Y"
.venv/bin/tfguard report   # print this week's report card
```

No AI needed: the rules engine answers every report-card question with no backend at all. Optional LLM backend (default: local Ollama):

```bash
ollama serve && ollama pull llama3.1   # or set TFG_AI_BASE_URL to any OpenAI-compatible API
```

## AI endpoints

```bash
# run it
tfguard serve            # listens on http://127.0.0.1:8647

# use it like the OpenAI API (any client works — set base URL + any key)
curl http://127.0.0.1:8647/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "tesla-family-guard",
       "messages": [{"role": "user", "content": "weekly report for the Model Y"}]}'

curl http://127.0.0.1:8647/v1/models
curl http://127.0.0.1:8647/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": "speeding on Wednesday night"}'
```

- `POST /v1/chat/completions` — OpenAI-shaped responses (streaming not supported); report-card questions are answered by the rules engine, the rest by your LLM backend if configured
- `GET /v1/models` — advertises the guard as a model
- `POST /v1/embeddings` — deterministic local feature-hashing embeddings (dim 384, zero external calls)
- Optional bearer <redacted> (`TFG_SERVER_API_KEY`) — clients authenticate exactly like OpenAI

**Privacy:** driving stats are sent **only** to the backend *you* configure. With `TFG_AI_MODE=never` (or no backend), nothing leaves your machine except Tesla API calls and your own ntfy.sh alerts.

## Tesla developer setup

1. Create an app at developer.tesla.com (free) — note the Client ID and Client Secret.
2. Scopes needed: `vehicle_device_data`, `vehicle_location` (reads only — this app issues no commands).
3. Run `tfguard setup`, then `tfguard auth` and follow the pairing docs at https://developer.tesla.com/docs/fleet-api#pairing (virtual key).

## `.env` reference

| Variable | Default | Meaning |
|---|---|---|
| `TFG_VEHICLES` | — | Cars as `name=VIN` pairs |
| `TFG_SPEED_LIMIT_MPH` | `75` | Speed that counts as speeding |
| `TFG_CURFEW_START` / `TFG_CURFEW_END` | `11:00 PM` / `5:00 AM` | Curfew window (12-hour words) |
| `TFG_QUIET_START` / `TFG_QUIET_END` | `10:00 PM` / `7:00 AM` | Quiet hours: non-safety alerts wait |
| `TFG_ALERT_COOLDOWN_MINUTES` | `60` | Minutes between repeat alerts |
| `TFG_NTFY_TOPIC` | — | Your private ntfy.sh topic for phone alerts |
| `TFG_GEOFENCES` | — | Allowed areas, written by `setup` (name + address, geocoded) |
| `TFG_SERVER_PORT` | `8647` | Report-card API port |
| `TFG_AI_MODE` | `auto` | `auto` / `always` / `never` — LLM backend use |
| `TFG_DRY_RUN` | `0` | `1` = never send live alerts |

You never hand-edit this file: `tfguard setup` asks plain-language questions and writes it.

## FAQ

**Does Tesla have a teen driver mode with alerts?**
Tesla has Speed Limit Mode (a cap) and Valet Mode, but neither alerts a parent or produces a report. Family Guard adds the alerts and the weekly report card.

**Will it wake my car and drain the battery?**
No. It only reads while the car is already awake (driving). It never issues wake-ups to measure anything.

**Does it control or limit the car?**
No — watch-only by design. It cannot change speed limits, lock, or stop the car. If you want a cap, use Tesla's built-in Speed Limit Mode alongside it.

**What if my teen drives at 2 AM?**
Curfew alerts are safety alerts: they go out immediately, even during quiet hours. Only geofence exits wait until morning.

**Will one long speeding stretch spam my phone?**
No — the cooldown (default 60 minutes) means one stretch = one alert.

**Do I need AI / Ollama / an API key?**
No. The rules engine answers every report-card question offline. The LLM backend is optional and only explains the week in free-form words.

**Where do alerts go?**
To your phone via ntfy.sh (free): install the ntfy app, pick a private topic name, subscribe. No account, no subscription.

## License

MIT — Raphael Malikian. Part of a series of free, open-source Tesla Fleet API apps.
