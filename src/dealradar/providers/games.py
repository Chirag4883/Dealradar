import sys
from urllib.parse import urlencode
from ..models import Offer, money
from ..http import APIError


class Games:
    def __init__(self, http):
        self.http = http
        self._stores_cache = None

    def _get_stores(self):
        if self._stores_cache is None:
            try:
                stores = self.http.request("GET", "https://www.cheapshark.com/api/1.0/stores")
                if isinstance(stores, list):
                    self._stores_cache = {
                        str(s["storeID"]): s["storeName"]
                        for s in stores
                        if isinstance(s, dict) and s.get("isActive") == 1
                    }
            except Exception:
                pass

            if not self._stores_cache:
                self._stores_cache = {
                    "1": "Steam",
                    "2": "GamersGate",
                    "3": "GreenManGaming",
                    "7": "GOG",
                    "25": "Epic Games",
                }
        return self._stores_cache

    def fetch(self, w):
        game_id = str(w.get("game_id", "")).strip()
        title_query = (w.get("titles") and w["titles"][0]) or w.get("id", "")
        stores = self._get_stores()
        allowed_stores = [str(s) for s in w.get("stores", [])]

        result = None

        # 1. Try fetching by game_id
        if game_id:
            try:
                res = self.http.request(
                    "GET", "https://www.cheapshark.com/api/1.0/games", params={"id": game_id}
                )
                if isinstance(res, dict) and isinstance(res.get("deals"), list):
                    result = res
            except APIError as e:
                print(f"[Games] ID lookup failed for {w.get('id')} ({e}); attempting title search.", file=sys.stderr)

        # 2. Fallback: Search by title if ID failed or returned 400
        if not result and title_query:
            try:
                search_res = self.http.request(
                    "GET", "https://www.cheapshark.com/api/1.0/games", params={"title": title_query, "limit": "1"}
                )
                if isinstance(search_res, list) and len(search_res) > 0:
                    matched_id = str(search_res[0].get("gameID", ""))
                    if matched_id:
                        res = self.http.request(
                            "GET", "https://www.cheapshark.com/api/1.0/games", params={"id": matched_id}
                        )
                        if isinstance(res, dict) and isinstance(res.get("deals"), list):
                            result = res
                            game_id = matched_id
            except APIError as e:
                print(f"[Games] Title search failed for {title_query}: {e}", file=sys.stderr)

        if not result or not isinstance(result.get("deals"), list):
            return []

        offers = []
        for row in result["deals"]:
            try:
                store_id = str(row.get("storeID", ""))
                if allowed_stores and store_id not in allowed_stores:
                    continue

                deal_id = row.get("dealID")
                if not deal_id:
                    continue

                sale_price = str(row.get("price", "999999"))
                game_title = (result.get("info") or {}).get("title") or title_query

                offers.append(
                    Offer(
                        "games",
                        f"{game_id}:{store_id}",
                        game_title,
                        money(sale_price),
                        "USD",
                        stores.get(store_id, f"Store {store_id}"),
                        "https://www.cheapshark.com/redirect?" + urlencode({"dealID": deal_id}),
                        True,
                        "PC game; USD listed price. Check region, DRM and checkout taxes. Link via CheapShark.",
                        True,
                    )
                )
            except Exception:
                continue

        return offers
