"""The setup wizard must produce a config the app can load — no developer
knowledge required from the (scripted) user. Geocoding is stubbed out:
the test answers an address and accepts the address-only fence."""
from tesla_family_guard.config import load_settings
from tesla_family_guard.setup import run_setup


def test_setup_writes_loadable_config(tmp_path, monkeypatch):
    monkeypatch.setattr("tesla_family_guard.setup._geocode", lambda a: None)
    answers = iter([
        "cid-123", "csecret-456",          # Tesla app credentials
        "Model Y", "VINY", "",             # cars (blank = done)
        "75", "11:00 PM", "5:00 AM",       # rules
        "10:00 PM", "7:00 AM", "60",
        "Home", "38556 31st St E, Palmdale, CA 93550", "5",  # place
        "my-secret-topic",                 # ntfy topic
        "1",                               # AI: built-in only
        "8647", "",                        # server port, no password
    ])
    out_lines = []
    env_path = tmp_path / ".env"
    run_setup(input_fn=lambda prompt="": next(answers),
              out=out_lines.append, env_path=str(env_path))
    assert env_path.exists()
    raw = env_path.read_text()
    assert "TFG_VEHICLES=Model Y=VINY" in raw
    assert "TFG_SPEED_LIMIT_MPH=75" in raw
    assert "TFG_CURFEW_START=11:00 PM" in raw
    assert "TFG_NTFY_TOPIC=my-secret-topic" in raw
    assert "TFG_AI_MODE=never" in raw
    assert "TFG_GEOFENCES=Home|38556 31st St E, Palmdale, CA 93550||5" in raw
    # The written config must load cleanly.
    env = {}
    for line in raw.splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    s = load_settings(env)
    assert s.vehicles[0].name == "Model Y"
    assert s.speed_limit_mph == 75
    assert s.geofences[0].name == "Home"
    assert s.geofences[0].latitude is None  # geocode stubbed: address-only


def test_setup_keeps_existing_config(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("TFG_VEHICLES=Model Y=VINY\n")
    answers = iter(["n"])
    run_setup(input_fn=lambda prompt="": next(answers), out=lambda *a: None,
              env_path=str(env_path))
    assert env_path.read_text() == "TFG_VEHICLES=Model Y=VINY\n"
