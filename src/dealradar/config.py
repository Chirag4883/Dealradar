import re
import tomllib
from datetime import date
from pathlib import Path
from .models import money, normalize

CABINS = {"ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"}
LOCALES = {("in", "INR"): ("₹", "INR"), ("us", "USD"): ("$", "US$", "USD"), ("gb", "GBP"): ("£", "GBP")}


class ConfigError(ValueError):
    """Invalid configuration.

    Every message is a static operator-facing string, optionally naming a key
    or watch id the operator wrote themselves. Messages never contain
    credentials, URLs, API payloads or offer data, so the CLI may log them.
    Errors raised anywhere else stay opaque; see cli.main.
    """


def load(path: str) -> dict:
    try:
        with Path(path).open("rb") as stream:
            config = tomllib.load(stream)
    except FileNotFoundError:
        raise ConfigError("configuration file not found: " + str(path)) from None
    except IsADirectoryError:
        raise ConfigError("configuration path is a directory: " + str(path)) from None
    except PermissionError:
        raise ConfigError("configuration file is not readable: " + str(path)) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("TOML syntax error: " + str(exc)) from None
    validate(config)
    return config


def only(obj, keys, what="table"):
    if not isinstance(obj, dict):
        raise ConfigError(what + " must be a table")
    unknown = sorted(set(obj) - set(keys.split()))
    if unknown:
        raise ConfigError("unknown configuration key: " + unknown[0])


def strings(value, what, nonempty=True):
    if not isinstance(value, list):
        raise ConfigError(what + " must be a list of strings")
    if nonempty and not value:
        raise ConfigError(what + " must not be empty")
    if any(not isinstance(x, str) or not x.strip() for x in value):
        raise ConfigError(what + " must contain only nonempty strings")


def text(container, key, what):
    """Return a required string, rejecting missing keys and wrong types alike."""
    if key not in container:
        raise ConfigError(what + " is required")
    if not isinstance(container[key], str):
        raise ConfigError(what + " must be a string")
    return container[key]


def isodate(container, key):
    value = text(container, key, key)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ConfigError(key + " must be a date in YYYY-MM-DD form")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ConfigError(key + " is not a real calendar date") from None


def whole(w, key, low, high):
    if type(w.get(key)) is not int or not low <= w[key] <= high:
        raise ConfigError(f"{key} must be a whole number from {low} to {high}")


def validate(c):
    only(c, "state channels policy watches", "the top-level configuration")
    if not isinstance(c.get("state", "state/dealradar.sqlite3"), str):
        raise ConfigError("state must be a path string")
    channels = c.get("channels", [])
    strings(channels, "channels", nonempty=False)
    if len(set(channels)) != len(channels) or set(channels) - {"telegram", "discord"}:
        raise ConfigError("channels must be a duplicate-free subset of 'telegram' and 'discord'")
    policy = c.get("policy", {})
    only(policy, "blocked_domains blocked_sellers", "policy")
    for key in ("blocked_domains", "blocked_sellers"):
        strings(policy.get(key, []), "policy." + key, nonempty=False)
    watches = c.get("watches")
    if not isinstance(watches, list) or not watches:
        raise ConfigError("at least one watch is required")
    ids = set()
    common = "id category currency max_price min_price enabled"
    categories = {
        "shopping": "query titles merchants gl price_prefix max_products",
        "games": "game_id titles stores",
        "flights": "origin destination departure return_date adults cabin max_stops carriers",
    }
    for index, w in enumerate(watches):
        label = "watch #" + str(index + 1)
        try:
            if not isinstance(w, dict):
                raise ConfigError("each watch must be a table")
            category = w.get("category")
            if category not in categories:
                raise ConfigError("category must be shopping, games or flights")
            only(w, common + " " + categories[category], "watch")
            identifier = text(w, "id", "id")
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identifier):
                raise ConfigError("id must be 1-64 characters from A-Z, a-z, 0-9, '_' and '-'")
            label = "watch '" + identifier + "'"
            if identifier in ids:
                raise ConfigError("duplicate watch id")
            ids.add(identifier)
            check(w, category)
        except ConfigError as exc:
            raise ConfigError(label + ": " + str(exc)) from None
        except KeyError as exc:
            raise ConfigError(label + ": required key " + repr(exc.args[0]) + " is missing") from None
        except ValueError as exc:
            raise ConfigError(label + ": " + str(exc)) from None
        except (TypeError, IndexError, AttributeError):
            raise ConfigError(label + ": a value has the wrong type") from None


def check(w, category):
    """Validate one watch. Raises ConfigError without context; validate adds the label."""
    if type(w.get("enabled", True)) is not bool:
        raise ConfigError("enabled must be true or false")
    if not re.fullmatch(r"[A-Z]{3}", text(w, "currency", "currency")):
        raise ConfigError("currency must be a three-letter uppercase ISO 4217 code")
    try:
        ceiling, floor = money(w.get("max_price")), money(w.get("min_price", 0))
    except ValueError:
        raise ConfigError("max_price and min_price must be nonnegative decimal amounts") from None
    if ceiling <= 0:
        raise ConfigError("max_price must be greater than zero")
    if floor > ceiling:
        raise ConfigError("min_price must not exceed max_price")

    if category in ("shopping", "games"):
        strings(w.get("titles"), "titles")
        if any(not normalize(t) or len(t) > 300 for t in w["titles"]):
            raise ConfigError("each title must contain letters or digits and be at most 300 characters")

    if category == "shopping":
        if not text(w, "query", "query").strip():
            raise ConfigError("query must not be blank")
        if not re.fullmatch(r"[a-z]{2}", text(w, "gl", "gl")):
            raise ConfigError("gl must be a two-letter lowercase country code")
        # Ambiguous $ symbols are accepted only for US/USD searches.
        if w.get("price_prefix") not in LOCALES.get((w["gl"], w["currency"]), ()):
            raise ConfigError("unsupported gl/currency/price_prefix combination; reviewed "
                              "combinations are in/INR '₹', us/USD '$' and gb/GBP '£'")
        if "max_products" in w:
            whole(w, "max_products", 1, 20)
        merchants = w.get("merchants")
        if not isinstance(merchants, list) or not merchants:
            raise ConfigError("merchants must be a nonempty list of {seller, domain} pairs")
        for merchant in merchants:
            only(merchant, "seller domain", "each merchant")
            if not normalize(text(merchant, "seller", "merchant seller")):
                raise ConfigError("merchant seller must contain letters or digits")
            if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}",
                                text(merchant, "domain", "merchant domain")):
                raise ConfigError("merchant domain must be a lowercase bare domain such as example.co.in")

    elif category == "games":
        if w["currency"] != "USD":
            raise ConfigError("games watches must use currency USD; CheapShark lists USD prices")
        if not re.fullmatch(r"[0-9]+", text(w, "game_id", "game_id")):
            raise ConfigError("game_id must be an official numeric Steam App ID string")
        strings(w.get("stores"), "stores")
        if any(not re.fullmatch(r"[0-9]+", x) for x in w["stores"]):
            raise ConfigError("each store must be a numeric CheapShark store ID string")

    elif category == "flights":
        for key in ("origin", "destination"):
            if not re.fullmatch(r"[A-Z]{3}", text(w, key, key)):
                raise ConfigError(key + " must be a three-letter uppercase IATA airport code")
        if w["origin"] == w["destination"]:
            raise ConfigError("origin and destination must be different airports")
        departure = isodate(w, "departure")
        if w.get("return_date") and isodate(w, "return_date") < departure:
            raise ConfigError("return_date must not precede departure")
        whole(w, "adults", 1, 9)
        whole(w, "max_stops", 0, 3)
        if text(w, "cabin", "cabin") not in CABINS:
            raise ConfigError("cabin must be ECONOMY, PREMIUM_ECONOMY, BUSINESS or FIRST")
        strings(w.get("carriers"), "carriers")
        if any(not re.fullmatch(r"[A-Z0-9]{2}", x) for x in w["carriers"]):
            raise ConfigError("each carrier must be a two-character uppercase IATA airline code")
