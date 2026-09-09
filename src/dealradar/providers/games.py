from urllib.parse import urlencode
from ..models import Offer, money
from ..http import APIError


class Games:
    def __init__(self, http):
        self.http = http
        self._stores_cache = None

    def _get_stores(self):
        if self._stores_cache is None:
            stores = self.http.request("GET", "https://www.cheapshark.com/api/1.0/stores")
            if not isinstance(stores, list):
                # Fallback mapping if stores API is rate-limited or blocked
                return {"1": "Steam", "2": "GamersGate", "3": "GreenManGaming", "7": "GOG", "25": "Epic Games"}
            self._stores_cache = {
                str(s["storeID"]): s["storeName"]
                for s in stores
                if isinstance(s, dict) and s.get("isActive") == 1
            }
        return self._stores_cache

    def fetch(self, w):
        game_id = str(w.get("game_id", "")).strip()
        if not game_id:
            return []

        result = self.http.request(
            "GET", "https://www.cheapshark.com/api/1.0/games", params={"id": game_id}
        )

        # When game_id is invalid or empty, CheapShark returns [] instead of a dict
        if not isinstance(result, dict) or "deals" not in result or not isinstance(result["deals"], list):
            return []

        names = self._get_stores()
        allowed_stores = [str(s) for s in w.get("stores", [])]

        offers = []
        for row in result["deals"]:
            try:
                store_id = str(row.get("storeID", ""))
                if allowed_stores and store_id not in allowed_stores:
                    continue
                if store_id not in names:
                    continue

                deal_id = row.get("dealID")
                if not deal_id:
                    continue

                deal = self.http.request(
                    "GET", "https://www.cheapshark.com/api/1.0/deals", params={"id": deal_id}
                )

                if not isinstance(deal, dict) or "gameInfo" not in deal:
                    continue

                info = deal["gameInfo"]
                if str(info.get("gameID", "")) != game_id or str(info.get("storeID", "")) != store_id:
                    continue

                offers.append(
                    Offer(
                        "games",
                        f"{game_id}:{store_id}",
                        info["name"],
                        money(info["salePrice"]),
                        "USD",
                        names.get(store_id, f"Store {store_id}"),
                        "https://www.cheapshark.com/redirect?" + urlencode({"dealID": deal_id}),
                        True,
                        "PC game; USD listed price. Check region, DRM and checkout taxes. Link via CheapShark.",
                        True,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        return offers
