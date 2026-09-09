import logging
from urllib.parse import urlencode

from ..http import APIError
from ..models import Offer, money, normalize


LOGGER = logging.getLogger(__name__)
CHEAPSHARK_API = "https://www.cheapshark.com/api/1.0"
CHEAPSHARK_REDIRECT = "https://www.cheapshark.com/redirect"
CHEAPSHARK_HEADERS = {
    "User-Agent": "DealRadar/1.0 (CheapShark API client)",
    "Accept": "application/json",
}
FALLBACK_STORES = {"1": "Steam"}
DETAILS = (
    "PC game; USD listed price. Check region, DRM and checkout taxes. "
    "Link via CheapShark."
)


class Games:
    def __init__(self, http):
        self.http = http
        self._stores_cache = None

    def _get_stores(self):
        """Return active stores, loading CheapShark metadata at most once."""
        if self._stores_cache is not None:
            return self._stores_cache

        # Store metadata improves labels but is not required to discover deals.
        # Keep a trusted fallback so /stores failures cannot disable Steam watches.
        stores = dict(FALLBACK_STORES)
        try:
            result = self.http.request(
                "GET",
                f"{CHEAPSHARK_API}/stores",
                headers=CHEAPSHARK_HEADERS,
            )
            if isinstance(result, list):
                for row in result:
                    if (
                        not isinstance(row, dict)
                        or row.get("isActive") not in (1, "1", True)
                    ):
                        continue
                    store_id = str(row.get("storeID", "")).strip()
                    store_name = row.get("storeName")
                    if (
                        store_id
                        and isinstance(store_name, str)
                        and store_name.strip()
                    ):
                        stores[store_id] = store_name.strip()
            else:
                LOGGER.warning(
                    "CheapShark store lookup returned an unexpected schema; "
                    "using built-in store names"
                )
        except APIError as exc:
            LOGGER.warning(
                "CheapShark store lookup failed: %s; using built-in store names",
                exc,
            )

        # A fallback result is cached too, so /stores is never retried per watch.
        self._stores_cache = stores
        return self._stores_cache

    def fetch(self, watch):
        """Find exact-title deals and verify them with an official Steam App ID."""
        watch_id = str(watch.get("id", "games"))
        steam_app_id = str(watch.get("game_id", "")).strip()
        allowed_stores = {
            str(value).strip() for value in watch.get("stores", []) if str(value).strip()
        }
        titles = [
            value.strip()
            for value in watch.get("titles", [])
            if isinstance(value, str) and value.strip()
        ]

        if not steam_app_id or not allowed_stores or not titles:
            LOGGER.warning(
                "CheapShark watch %s has no Steam App ID, stores or title",
                watch_id,
            )
            return []

        stores = self._get_stores()
        trusted_stores = allowed_stores.intersection(stores)
        if not trusted_stores:
            LOGGER.warning(
                "CheapShark watch %s has no known active stores",
                watch_id,
            )
            return []

        try:
            result = self.http.request(
                "GET",
                f"{CHEAPSHARK_API}/deals",
                params={
                    "title": titles[0],
                    "exact": "1",
                    "storeID": ",".join(sorted(trusted_stores)),
                    "pageSize": "60",
                },
                headers=CHEAPSHARK_HEADERS,
            )
        except APIError as exc:
            LOGGER.warning("CheapShark deal lookup failed for %s: %s", watch_id, exc)
            return []

        if not isinstance(result, list):
            LOGGER.warning(
                "CheapShark deal lookup returned an unexpected schema for %s",
                watch_id,
            )
            return []

        allowed_titles = {normalize(title) for title in titles}
        offers = []
        for row in result:
            try:
                if not isinstance(row, dict):
                    continue

                store_id = str(row.get("storeID", "")).strip()
                returned_app_id = str(row.get("steamAppID", "")).strip()
                title = row.get("title")
                deal_id = row.get("dealID")

                if (
                    store_id not in trusted_stores
                    or returned_app_id != steam_app_id
                    or not isinstance(title, str)
                    or normalize(title) not in allowed_titles
                    or not isinstance(deal_id, str)
                    or not deal_id
                ):
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
                        + urlencode({"dealID": deal_id}, safe="%"),
                        available=True,
                        details=DETAILS,
                        verified=True,
                    )
                )
            except (TypeError, ValueError):
                # Ignore one malformed deal without discarding other valid rows.
                continue

        return offers
