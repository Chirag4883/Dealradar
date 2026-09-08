import hashlib
import json
from datetime import date
from ..models import Offer, money
from ..http import APIError, secret


class Flights:
    def __init__(self, http):
        self.http = http

    def fetch(self, w):
        if date.fromisoformat(w["departure"]) < date.today():
            raise APIError("flight departure has expired")
        base = "https://api.amadeus.com"  # Production only: sandbox fares must never trigger alerts.
        token = self.http.request("POST", base + "/v1/security/oauth2/token", form={
            "grant_type": "client_credentials", "client_id": secret("AMADEUS_CLIENT_ID"),
            "client_secret": secret("AMADEUS_CLIENT_SECRET")})["access_token"]
        headers = {"Authorization": "Bearer " + token}
        params = {"originLocationCode": w["origin"], "destinationLocationCode": w["destination"],
                  "departureDate": w["departure"], "adults": w["adults"], "travelClass": w["cabin"],
                  "currencyCode": w["currency"], "includedAirlineCodes": ",".join(w["carriers"]), "max": 20}
        if w.get("return_date"):
            params["returnDate"] = w["return_date"]
        result = self.http.request("GET", base + "/v2/shopping/flight-offers", params=params, headers=headers)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise APIError("flight search schema changed")
        offers = []
        for row in result["data"]:
            candidate = self.parse(row, w)
            if candidate is None or candidate.price > money(w["max_price"]):
                continue
            # A search price is insufficient: reprice via Flight Offers Price immediately.
            priced = self.http.request("POST", base + "/v1/shopping/flight-offers/pricing", headers=headers,
                data={"data": {"type": "flight-offers-pricing", "flightOffers": [row]}})
            for refreshed in priced.get("data", {}).get("flightOffers", []):
                offer = self.parse(refreshed, w)
                if offer and offer.identity == candidate.identity:
                    offers.append(offer)
        return offers

    @staticmethod
    def parse(row, w):
        try:
            if row.get("numberOfBookableSeats", 0) < w["adults"]:
                return None
            routes = [(w["origin"], w["destination"], w["departure"])]
            if w.get("return_date"):
                routes.append((w["destination"], w["origin"], w["return_date"]))
            itineraries = row["itineraries"]
            if len(itineraries) != len(routes):
                return None
            signature, segment_ids, codes = [], set(), set()
            for itinerary, (origin, destination, departure) in zip(itineraries, routes):
                segments = itinerary["segments"]
                if not segments or len(segments) - 1 > w["max_stops"]:
                    return None
                if segments[0]["departure"]["iataCode"] != origin or segments[-1]["arrival"]["iataCode"] != destination or segments[0]["departure"]["at"][:10] != departure:
                    return None
                previous = None
                for s in segments:
                    if s.get("numberOfStops", 0) != 0:
                        return None
                    if previous and previous != s["departure"]["iataCode"]:
                        return None
                    previous = s["arrival"]["iataCode"]
                    operating = s.get("operating", {}).get("carrierCode")
                    if not operating or s["carrierCode"] not in w["carriers"] or operating not in w["carriers"]:
                        return None
                    codes.update([s["carrierCode"], operating])
                    segment_ids.add(s["id"])
                    signature.append([s["departure"], s["arrival"], s["carrierCode"], operating, s["number"]])
            validating = row["validatingAirlineCodes"]
            if not validating or any(x not in w["carriers"] for x in validating):
                return None
            codes.update(validating)
            travelers = row["travelerPricings"]
            if len(travelers) != w["adults"] or len({t["travelerId"] for t in travelers}) != w["adults"]:
                return None
            for traveler in travelers:
                fares = traveler["fareDetailsBySegment"]
                if traveler["travelerType"] != "ADULT" or {f["segmentId"] for f in fares} != segment_ids or any(f["cabin"] != w["cabin"] for f in fares):
                    return None
            price = money(row["price"]["grandTotal"])
            if price <= 0:
                return None
            identity = hashlib.sha256(json.dumps([signature, w["adults"], w["cabin"]], sort_keys=True).encode()).hexdigest()
            title = f'{w["origin"]} → {w["destination"]} | {w["departure"]}'
            if w.get("return_date"):
                title += ' / return ' + w["return_date"]
            return Offer("flights", identity, title, price, row["price"]["currency"], ", ".join(sorted(codes)),
                None, True, f'{w["adults"]} adult(s), {w["cabin"]}; total for all travelers. Repriced Amadeus quote; optional bags/ancillaries extra. No booking link.', True)
        except (KeyError, TypeError, ValueError, IndexError):
            return None
