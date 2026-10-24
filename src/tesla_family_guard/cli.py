"""CLI: tfguard setup | auth | serve | ask | report | monitor | simulate

Safety posture: `monitor` defaults to a dry-run preview — it prints
exactly which alerts WOULD go to the parent's phone and sends nothing.
Pass --live to actually post them (and only after the preview).
"""
from __future__ import annotations

import argparse
import os
import sys

from .config import ConfigError, load_settings

__version__ = "0.1.0"


def _setup_logging(verbose: bool) -> None:
    import logging
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")


def _client(settings):
    from .tesla_client import TeslaClient
    return TeslaClient(settings.client_id, settings.client_secret,
                       region=settings.region, redirect_uri=settings.redirect_uri,
                       token_file=settings.token_file)


def cmd_auth(args, settings) -> int:
    client = _client(settings)
    print("Open this URL in your browser and authorize:")
    print(client.authorize_url())
    print("Virtual-key pairing: https://developer.tesla.com/docs/fleet-api#pairing")
    return 0


def cmd_setup(args, settings) -> int:
    from .setup import run_setup
    run_setup()
    return 0


def _demo_settings(settings):
    """Demo-week settings: pretend fence around Palmdale, defaults otherwise."""
    from .simulator import demo_fences
    settings.geofences = demo_fences()
    return settings


def cmd_serve(args, settings) -> int:
    from .server import serve
    from .service import FamilyGuardService
    from .simulator import run_demo_week
    # The served stats come from the driving log once a real week exists;
    # until then the demo week stands in so the endpoint is testable.
    _, _, stats = run_demo_week(_demo_settings(settings))
    service = FamilyGuardService(settings, stats_provider=lambda: stats)
    print("Driving stats go ONLY to your configured LLM backend "
          f"(TFG_AI_BASE_URL={settings.ai_base_url or 'none'}); "
          "the rules engine answers report cards with no backend at all.")
    print("This app only watches and alerts — it never commands a car.")
    serve(service)
    return 0


def cmd_ask(args, settings) -> int:
    from .service import FamilyGuardService
    from .simulator import run_demo_week
    _, _, stats = run_demo_week(_demo_settings(settings))
    service = FamilyGuardService(settings, stats_provider=lambda: stats)
    body = {"model": settings.model_id,
            "messages": [{"role": "user", "content": args.question}]}
    resp = service.chat_completions(body)
    print(resp["choices"][0]["message"]["content"])
    return 0


def cmd_report(args, settings) -> int:
    from .guard import report_card_text
    from .simulator import run_demo_week
    _, _, stats = run_demo_week(_demo_settings(settings))
    print("(Demo week — connect a car and run `tfguard monitor` to build")
    print("a real week. The rules are identical; only the drives are pretend.)")
    print("")
    for st in stats.values():
        print(report_card_text(st, settings))
    return 0


def cmd_monitor(args, settings) -> int:
    """Preview (default) or send this week's alerts. Live sends need the
    parent's explicit --live flag AND a confirmation."""
    from .guard import send_ntfy_alert
    from .simulator import run_demo_week
    _, alerts, _ = run_demo_week(_demo_settings(settings))
    if not alerts:
        print("No alerts this week — nothing to send.")
        return 0
    print("This is what would go to the parent's phone:")
    for a in alerts:
        print(f"  - {a.plain()}")
    if not args.live:
        print("")
        print("Dry-run preview only — nothing was sent.")
        print("Happy with it? Re-run with `tfguard monitor --live` to send.")
        return 0
    if settings.dry_run:
        print("TFG_DRY_RUN is set — refusing to send live. Unset it first.")
        return 2
    answer = input("Send these alerts for real? Type YES to confirm: ").strip()
    if answer != "YES":
        print("Not confirmed — nothing sent.")
        return 0
    if not settings.ntfy_topic:
        print("No ntfy topic configured — run `tfguard setup` and add one,")
        print("then re-run. Nothing was sent.")
        return 2
    sent = sum(1 for a in alerts if send_ntfy_alert(settings.ntfy_topic, a))
    print(f"Sent {sent} of {len(alerts)} alert(s) to topic "
          f"{settings.ntfy_topic}.")
    if sent < len(alerts):
        print("Some alerts didn't go through — check the topic name and")
        print("your connection, then re-run `tfguard monitor --live`.")
    return 0


def cmd_simulate(_args, settings) -> int:
    from .simulator import timeline_lines
    for line in timeline_lines(_demo_settings(settings)):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tfguard",
        description="Per-driver speed, geofence and curfew alerts + weekly "
                    "report cards for your family's Teslas.")
    p.add_argument("--version", action="version", version=f"tfguard {__version__}")
    p.add_argument("--env-file", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Guided first-run setup (plain-language questions)")
    sub.add_parser("auth", help="Authorize with your Tesla account (one-time)")
    sub.add_parser("serve", help="Run the OpenAI-compatible report-card API server")
    ask_p = sub.add_parser("ask", help="One-shot report-card question (demo week)")
    ask_p.add_argument("question", help="e.g. 'weekly report for the Model Y'")
    sub.add_parser("report", help="Print this week's report card (demo week)")
    mon_p = sub.add_parser("monitor", help="Preview (default) or send alerts")
    mon_p.add_argument("--live", action="store_true",
                       help="Actually send alerts (asks for confirmation)")
    sub.add_parser("simulate", help="Demo week timeline (no API calls)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    env = dict(os.environ)
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
        env = dict(os.environ)
    else:
        from dotenv import load_dotenv
        load_dotenv(override=False)
        env = dict(os.environ)
    try:
        settings = load_settings(env)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    handlers = {"setup": cmd_setup, "auth": cmd_auth, "serve": cmd_serve,
                "ask": cmd_ask, "report": cmd_report, "monitor": cmd_monitor,
                "simulate": cmd_simulate}
    return handlers[args.command](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
