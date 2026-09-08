import argparse
import json
import sys
from collections import Counter
from . import __version__
from .config import ConfigError, load
from .http import HTTP
from .notify import Notifier, render
from .policy import reject
from .providers import build
from .state import State, locked


def event(name, **fields):
    print(json.dumps({"event": name, **fields}, sort_keys=True), flush=True)


def run(config, dry_run=False, providers=None, notifiers=None, state=None):
    http = HTTP()
    providers = providers if providers is not None else build(http)
    notifiers = notifiers if notifiers is not None else ([] if dry_run else [Notifier(http, c) for c in config.get("channels", [])])
    if not dry_run and not notifiers:
        raise ConfigError("set channels to at least one of 'telegram' or 'discord' before running")
    errors = 0
    for watch in config["watches"]:
        if not watch.get("enabled", True):
            continue
        counts = Counter()
        try:
            offers = providers[watch["category"]].fetch(watch)
            # Stable cheapest-first order suppresses inferior offers from the same SKU/store.
            for offer in sorted(offers, key=lambda x: (x.price, x.identity, x.seller)):
                reason = reject(offer, watch, config.get("policy", {}))
                if reason:
                    counts[reason] += 1
                    continue
                if dry_run:
                    counts["eligible"] += 1
                    event("candidate", watch=watch["id"], price=str(offer.price), currency=offer.currency)
                    continue
                for notifier in notifiers:
                    try:
                        message = render(offer, watch, notifier.channel)
                        key = state.reserve(watch, offer, notifier)
                        if key is None:
                            counts["suppressed"] += 1
                            continue
                        notifier.send(message)
                        state.sent(key)
                        counts["sent"] += 1
                    except Exception as exc:
                        # No raw exception strings: URLs may contain API keys/webhook tokens.
                        errors += 1
                        event("delivery_error", watch=watch["id"], channel=notifier.channel, error_type=type(exc).__name__)
            event("watch_complete", watch=watch["id"], counts=dict(counts))
        except Exception as exc:
            errors += 1
            event("provider_error", watch=watch["id"], error_type=type(exc).__name__)
    pending = len(state.pending()) if state else 0
    event("run_complete", errors=errors, unresolved_deliveries=pending, dry_run=dry_run)
    return 1 if errors or pending else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dealradar")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--version", action="version", version="dealradar " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--dry-run", action="store_true")
    commands.add_parser("pending")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("delivery_id")
    resolve.add_argument("--action", choices=["delivered", "retry"], required=True)
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
        if args.command == "validate":
            event("config_valid", watches=len(config["watches"]))
            return 0
        if args.command == "run" and args.dry_run:
            return run(config, dry_run=True)
        path = config.get("state", "state/dealradar.sqlite3")
        with locked(path):
            state = State(path)
            try:
                if args.command == "pending":
                    event("pending", deliveries=state.pending())
                    return 0
                if args.command == "resolve":
                    state.resolve(args.delivery_id, args.action)
                    event("delivery_resolved", action=args.action)
                    return 0
                return run(config, state=state)
            finally:
                state.close()
    except ConfigError as exc:
        # Only ConfigError messages are logged: they are static operator-facing
        # strings by construction. Every other error stays opaque because
        # provider and delivery messages can embed API keys or webhook tokens.
        event("fatal", error_type="ConfigError", error=str(exc))
        return 2
    except Exception as exc:
        event("fatal", error_type=type(exc).__name__)
        return 2


if __name__ == "__main__":
    sys.exit(main())
