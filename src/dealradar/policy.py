import re
from urllib.parse import urlsplit
from .models import normalize, money

ACCESSORIES = {"case", "cases", "cover", "covers", "cable", "cables", "adapter", "adapters",
               "protector", "replacement", "refurbished", "renewed", "used", "rental", "replica"}


def host(url):
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return None
        if not p.hostname or not p.hostname.isascii() or "\\" in url or any(ord(c) <= 32 for c in url):
            return None
        return p.hostname.lower().rstrip(".")
    except (ValueError, TypeError):
        return None


def domain_matches(hostname, domain):
    domain = domain.lower().rstrip(".")
    return hostname == domain or hostname.endswith("." + domain)


def title_matches(title, watch):
    normalized = normalize(title)
    if watch["category"] == "shopping" and set(normalized.split()) & ACCESSORIES:
        return False
    return normalized in {normalize(t) for t in watch["titles"]}


def reject(offer, watch, policy):
    if offer.provider != watch["category"] or not offer.verified:
        return "unverified"
    if not offer.available:
        return "unavailable"
    if offer.currency != watch["currency"]:
        return "currency"
    if not offer.price.is_finite() or not money(watch.get("min_price", 0)) <= offer.price <= money(watch["max_price"]):
        return "price"
    seller = normalize(offer.seller)
    if not seller:
        return "unknown_seller"
    # Substring block matching deliberately favors false negatives over trust bypasses.
    if any(normalize(x) in seller for x in policy.get("blocked_sellers", [])):
        return "blocked_seller"
    hostname = host(offer.url) if offer.url else None
    if offer.url and not hostname:
        return "invalid_url"
    if hostname and any(domain_matches(hostname, d) for d in policy.get("blocked_domains", [])):
        return "blocked_domain"
    if watch["category"] == "shopping":
        if not hostname or not any(seller == normalize(m["seller"]) and domain_matches(hostname, m["domain"]) for m in watch["merchants"]):
            return "untrusted_merchant"
        if not title_matches(offer.title, watch):
            return "title"
    elif watch["category"] == "games":
        if not title_matches(offer.title, watch):
            return "title"
        if hostname != "www.cheapshark.com":
            return "untrusted_aggregator"
    elif offer.url:
        return "unexpected_flight_url"
    return None
