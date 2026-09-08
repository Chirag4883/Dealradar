from ..http import APIError, secret
from ..models import Offer, money, normalize
from ..policy import title_matches, host


class Shopping:
    def __init__(self, http):
        self.http = http

    def search(self, **params):
        result = self.http.request("GET", "https://serpapi.com/search.json", params={
            "api_key": secret("SERPAPI_API_KEY"), "no_cache": "true", **params})
        if not isinstance(result, dict) or result.get("error"):
            raise APIError("shopping API error")
        return result

    def fetch(self, w):
        search = self.search(engine="google_shopping", q=w["query"], gl=w["gl"], hl="en")
        rows = search.get("shopping_results")
        if not isinstance(rows, list):
            raise APIError("shopping results schema changed")
        offers = []
        count = 0
        for row in rows:
            if not isinstance(row, dict) or not title_matches(row.get("title", ""), w):
                continue
            token = row.get("immersive_product_page_token")
            if not token:
                continue
            if count >= w.get("max_products", 5):
                break
            count += 1
            product = self.search(engine="google_immersive_product", page_token=token).get("product_results")
            if not isinstance(product, dict) or not isinstance(product.get("stores"), list):
                raise APIError("merchant results schema changed")
            for store in product["stores"]:
                try:
                    # Never substitute the parent's title for a merchant's missing SKU title.
                    if not title_matches(store["title"], w):
                        continue
                    if any(store.get(k) for k in ("coupon", "monthly_payment_duration", "installments_description", "down_payment", "second_hand_condition")):
                        continue
                    details = " ".join(store.get("details_and_offers", []))
                    tokens = normalize(details + " " + store["title"])
                    if any(x in tokens for x in ("out of stock", "preorder", "pre order", "trade in", "subscription", "installment", "membership", "with plan")):
                        continue
                    if "in stock" not in normalize(details):
                        continue
                    if not str(store["total"]).strip().startswith(w["price_prefix"]):
                        continue
                    price = money(store["extracted_total"])
                    if price <= 0:
                        continue
                    identity = "|".join([normalize(store["title"]), normalize(store["name"]), host(store["link"]) or ""])
                    offers.append(Offer("shopping", identity, store["title"], price,
                                        w["currency"], store["name"], store["link"], True,
                                        "Merchant total estimate; verify taxes, delivery and condition at checkout.", True))
                except (KeyError, TypeError, ValueError):
                    continue
        return offers
