import sys
from urllib.parse import urlencode
from ..models import Offer, money
from ..http import APIError


class Games:
    def __init__(self, http):
        self.http = http

    def fetch(self, w):
        game_id = str(w.get("game_id", ""))
        print(f"\n================ [DIAGNOSTIC START: {w.get('id')}] ================", file=sys.stderr)
        print(f"Target game_id: {game_id!r}", file=sys.stderr)

        # 1. Fetch Game Overview
        try:
            result = self.http.request(
                "GET", "https://www.cheapshark.com/api/1.0/games", params={"id": game_id}
            )
            print(f"Games endpoint type: {type(result)}", file=sys.stderr)
            if isinstance(result, dict):
                print(f"Games keys: {list(result.keys())}", file=sys.stderr)
                print(f"Deals field type: {type(result.get('deals'))}", file=sys.stderr)
                if isinstance(result.get("deals"), list):
                    print(f"Number of deals found: {len(result['deals'])}", file=sys.stderr)
            else:
                print(f"Games response raw preview: {repr(result)[:300]}", file=sys.stderr)
        except Exception as err:
            print(f"EXCEPTION querying /games: {type(err).__name__}: {err}", file=sys.stderr)
            raise

        # 2. Fetch Stores Directory
        try:
            stores = self.http.request("GET", "https://www.cheapshark.com/api/1.0/stores")
            print(f"Stores endpoint type: {type(stores)}", file=sys.stderr)
            if isinstance(stores, list):
                print(f"Total active stores received: {len(stores)}", file=sys.stderr)
            else:
                print(f"Stores response raw preview: {repr(stores)[:300]}", file=sys.stderr)
        except Exception as err:
            print(f"EXCEPTION querying /stores: {type(err).__name__}: {err}", file=sys.stderr)
            raise

        # 3. Evaluate Schema Validation Check
        schema_checks = {
            "result_is_dict": isinstance(result, dict),
            "info_is_dict": isinstance(result.get("info"), dict) if isinstance(result, dict) else False,
            "deals_is_list": isinstance(result.get("deals"), list) if isinstance(result, dict) else False,
            "stores_is_list": isinstance(stores, list),
        }
        print(f"Schema checks: {schema_checks}", file=sys.stderr)

        if not all(schema_checks.values()):
            failed = [k for k, v in schema_checks.items() if not v]
            print(f"FAILED CHECKS: {failed}", file=sys.stderr)
            print(f"================ [DIAGNOSTIC END: {w.get('id')}] ================\n", file=sys.stderr)
            raise APIError(f"games schema changed: failed {failed}")

        names = {str(s["storeID"]): s["storeName"] for s in stores if isinstance(s, dict) and s.get("isActive") == 1}
        offers = []

        for row in result["deals"]:
            try:
                store_id = str(row.get("storeID", ""))
                allowed_stores = [str(s) for s in w.get("stores", [])]
                if store_id not in allowed_stores or store_id not in names:
                    continue

                deal_id = row.get("dealID")
                deal = self.http.request("GET", "https://www.cheapshark.com/api/1.0/deals", params={"id": deal_id})
                
                info = deal.get("gameInfo", {})
                if str(info.get("gameID")) != game_id or str(info.get("storeID")) != store_id:
                    continue

                offers.append(
                    Offer(
                        "games",
                        f"{game_id}:{store_id}",
                        info.get("name", "Unknown Game"),
                        money(info.get("salePrice", "0")),
                        "USD",
                        names[store_id],
                        "https://www.cheapshark.com/redirect?" + urlencode({"dealID": deal_id}),
                        True,
                        "PC game; USD listed price. Check region, DRM and checkout taxes. Link via CheapShark.",
                        True,
                    )
                )
            except Exception as row_err:
                print(f"Row parsing warning for deal {row.get('dealID')}: {row_err}", file=sys.stderr)
                continue

        print(f"Successfully generated {len(offers)} offers.", file=sys.stderr)
        print(f"================ [DIAGNOSTIC END: {w.get('id')}] ================\n", file=sys.stderr)
        return offers
