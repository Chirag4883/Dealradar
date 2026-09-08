from urllib.parse import urlencode
from ..models import Offer, money
from ..http import APIError


class Games:
    def __init__(self, http):
        self.http = http

    def fetch(self, w):
        # Catalogue ID prevents sequels/DLC being confused with the requested game.
        result = self.http.request("GET", "https://www.cheapshark.com/api/1.0/games", params={"id": w["game_id"]})
        stores = self.http.request("GET", "https://www.cheapshark.com/api/1.0/stores")
        if not isinstance(result, dict) or not isinstance(result.get("info"), dict) or not isinstance(result.get("deals"), list) or not isinstance(stores, list):
            raise APIError("games schema changed")
        names = {str(s["storeID"]): s["storeName"] for s in stores if s.get("isActive") == 1}
        offers = []
        for row in result["deals"]:
            try:
                store_id = str(row["storeID"])
                if store_id not in w["stores"] or store_id not in names:
                    continue
                # Re-read the exact deal before alerting; expired deals have no usable gameInfo.
                deal = self.http.request("GET", "https://www.cheapshark.com/api/1.0/deals", params={"id": row["dealID"]})
                info = deal["gameInfo"]
                if str(info["gameID"]) != w["game_id"] or str(info["storeID"]) != store_id:
                    continue
                offers.append(Offer("games", w["game_id"] + ":" + store_id, info["name"], money(info["salePrice"]),
                                    "USD", names[store_id], "https://www.cheapshark.com/redirect?" + urlencode({"dealID": row["dealID"]}),
                                    True, "PC game; USD listed price. Check region, DRM and checkout taxes. Link via CheapShark.", True))
            except (KeyError, TypeError, ValueError):
                continue
        return offers
