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
                return {"1": "Steam", "2": "GamersGate", "3": "GreenManGaming", "7": "GOG", "25": "Epic Games"}
            self._stores_cache = {
                str(s.get("storeID")): s.get("storeName")
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

        if not isinstance(result, dict):
            return []

        deals_list = result.get("deals")
        if not isinstance(deals_list, list):
            return []

        names = self._get_stores()
        allowed_stores = [str(s) for s in w.get("stores", [])]

        offers = []
        for row in deals_list:
            try:
                store_id = str(row.get("storeID", ""))
                if allowed_stores and store_id not in allowed_stores:
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
                # Normalize both to string to avoid int vs str type inequality bugs
                returned_game_id = str(info.get("gameID", ""))
                returned_store_id = str(info.get("storeID", ""))

                if returned_game_id != game_id or returned_store_id != store_id:
                    continue

                sale_price = str(info.get("salePrice", "0"))
                game_title = info.get("name") or (w.get("titles") and w["titles"][0]) or "Game Deal"

                offers.append(
                    Offer(
                        "games",
                        f"{game_id}:{store_id}",
                        game_title,
                        money(sale_price),
                        "USD",
                        names.get(store_id, f"Store {store_id}"),
                        "https://www.cheapshark.com/redirect?" + urlencode({"dealID": deal_id}),
                        True,
                        "PC game; USD listed price. Check region, DRM and checkout taxes. Link via CheapShark.",
                        True,
                    )
                )
            except Exception:
                continue

        return offers
