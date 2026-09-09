import logging
from urllib.parse import urlencode

from ..http import APIError
from ..models import Offer, money


LOGGER = logging.getLogger(__name__)
CHEAPSHARK_API = "https://www.cheapshark.com/api/1.0"
CHEAPSHARK_REDIRECT = "https://www.cheapshark.com/redirect"
DETAILS = (
    "PC game; USD listed price. Check region, DRM and checkout taxes. "
    "Link via CheapShark."
)


class Games:
    def __init__(self, http):
        self.http = http
        self._stores_cache = None
        self._stores_loaded = False

    def _get_stores(self):
        """Return active CheapShark stores, requesting the catalogue once per run."""
        if self._stores_loaded:
            return self._stores_cache

        # Cache failures as well as successes so a CheapShark outage does not cause
        # one /stores request for every configured game.
        self._stores_loaded = True
        try:
            result = self.http.request("GET", f"{CHEAPSHARK_API}/stores")
        except APIError as exc:
            LOGGER.warning("CheapShark store lookup failed: %s", exc)
            self._stores_cache = None
            return None

        if not isinstance(result, list):
            LOGGER.warning("CheapShark store lookup returned an unexpected schema")
            self._stores_cache = None
            return None

        stores = {}
        for row in result:
            if not isinstance(row, dict) or row.get("isActive") not in (1, "1", True):
                continue
            store_id = str(row.get("storeID", "")).strip()
            store_name = row.get("storeName")
            if store_id and isinstance(store_name, str) and store_name.strip():
                stores[store_id] = store_name.strip()

        if not stores:
            LOGGER.warning("CheapShark store lookup returned no active stores")
            self._stores_cache = None
            return None

        self._stores_cache = stores
        return self._stores_cache

    def fetch(self, watch):
        """Discover current deals using an official Steam App ID.

        CheapShark's internal game IDs are intentionally not used: they are not
        stable identifiers and an invalid one makes the API return HTTP 400.
        Any failure is isolated to this watch so the CLI can continue scanning.
        """
        watch_id = str(watch.get("id", "games"))
        steam_app_id = str(watch.get("game_id", "")).strip()
        allowed_stores = {str(value).strip() for value in watch.get("stores", [])}

        if not steam_app_id or not allowed_stores:
            LOGGER.warning("CheapShark watch %s has no Steam App ID or stores", watch_id)
            return []

        try:
            stores = self._get_stores()
            if stores is None:
                return []

            result = self.http.request(
                "GET",
                f"{CHEAPSHARK_API}/deals",
                params={
                    "steamAppID": steam_app_id,
                    "storeID": ",".join(sorted(allowed_stores)),
                    "pageSize": "60",
                },
            )
        except APIError as exc:
            LOGGER.warning("CheapShark lookup failed for %s: %s", watch_id, exc)
            return []

        if not isinstance(result, list):
            LOGGER.warning("CheapShark lookup returned an unexpected schema for %s", watch_id)
            return []

        offers = []
        for row in result:
            try:
                if not isinstance(row, dict):
                    continue

                store_id = str(row.get("storeID", "")).strip()
                returned_app_id = str(row.get("steamAppID", "")).strip()
                if (
                    store_id not in allowed_stores
                    or store_id not in stores
                    or returned_app_id != steam_app_id
                ):
                    continue

                deal_id = row.get("dealID")
                title = row.get("title")
                if not isinstance(deal_id, str) or not deal_id:
                    continue
                if not isinstance(title, str) or not title.strip():
                    continue

                offers.append(
                    Offer(
                        provider="games",
                        identity=f"{steam_app_id}:{store_id}",
                        title=title.strip(),
                        price=money(row.get("salePrice")),
                        currency="USD",
                        seller=stores[store_id],
                        url=f"{CHEAPSHARK_REDIRECT}?"
                        + urlencode({"dealID": deal_id}),
                        available=True,
                        details=DETAILS,
                        verified=True,
                    )
                )
            except (TypeError, ValueError):
                # One malformed deal must not discard other valid matches.
                continue

        return offers
