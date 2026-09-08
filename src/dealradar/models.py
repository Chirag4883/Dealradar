from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol
import re
import unicodedata


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", value).casefold()))


def money(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("invalid price")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid price") from None
    if not result.is_finite() or result < 0:
        raise ValueError("invalid price")
    return result


@dataclass(frozen=True)
class Offer:
    provider: str
    identity: str
    title: str
    price: Decimal
    currency: str
    seller: str
    url: str | None
    available: bool
    details: str = ""
    verified: bool = False


class Provider(Protocol):
    def fetch(self, watch: dict) -> list[Offer]: ...
