"""Aviasales live data through the Travelpayouts Data API (free, needs a token).

- Prices: /aviasales/v3/prices_for_dates, the cheapest tickets Aviasales users found recently
  for a route and date. Results are paged (limit/page) and cached for 15 minutes.
- Reference data (no token needed): cities.json in English and Russian, airlines.json. The
  cities give IATA codes for any city the user names and time zones for local arrival times.

Records are mapped to the mock flight schema. The Data API does not report baggage or seats
left, so those fields are None and the Flights module says so instead of guessing. Booking
is held inside SuperChat and links to Aviasales to buy the ticket (no payment here)."""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config, nlp
from ..apiclient import ApiClient
from ..repositories import DataSourceError

log = logging.getLogger("superchat.travelpayouts")
PAGE_SIZE = 30
MAX_PAGES = 2
# The mock data uses airport codes; the API searches better with metropolitan city codes.
CITY_CODES = {"SVO": "MOW"}
_AZ_SUFFIXES = ("ndan", "nden", "dan", "den", "tan", "ten", "ya", "ye", "na", "ne", "a", "e")


class TravelpayoutsRepository:
    source = "Aviasales (Travelpayouts Data API)"

    def __init__(self, token, client=None, data_client=None):
        if not token:
            raise DataSourceError("TRAVELPAYOUTS_TOKEN is not set")
        self.api = client or ApiClient("aviasales", "https://api.travelpayouts.com",
                                       headers={"X-Access-Token": token}, min_interval=0.3)
        self.data = data_client or ApiClient("travelpayouts-data", "https://api.travelpayouts.com",
                                             min_interval=0.1, timeout=30)
        self._items = {}
        self.reservations = []
        self._cities = self._names = self._airlines = None

    # ---------- reference data ----------

    def _reference(self):
        if self._cities is not None:
            return
        cities = {}
        names = {}
        for lang in ("en", "ru"):
            for c in self.data.get_json(f"/data/{lang}/cities.json", ttl=24 * 3600):
                if not c.get("has_flightable_airport") or not c.get("code"):
                    continue
                if lang == "en":
                    cities[c["code"]] = {"code": c["code"], "city": c.get("name") or c["code"],
                                         "tz": c.get("time_zone")}
                forms = [c.get("name") or ""] + [v.removeprefix("в ").removeprefix("во ")
                                                 for v in (c.get("cases") or {}).values() if v]
                for form in forms:
                    names.setdefault(nlp.fold(form).strip(), c["code"])  # first (main) city wins on clashes
        airlines = {a["code"]: a.get("name") or a["code"]
                    for a in self.data.get_json("/data/en/airlines.json", ttl=24 * 3600) if a.get("code")}
        self._cities, self._names, self._airlines = cities, names, airlines

    def resolve_city(self, word):
        """IATA city code for a city name in English or Russian, or Azerbaijani with a case ending
        ('Londona', 'Parisdən'); None when unknown."""
        self._reference()
        word = nlp.fold(word).strip()
        if word in self._names:
            return self._names[word]
        for suffix in _AZ_SUFFIXES:
            stem = word.removesuffix(suffix)
            if stem != word and len(stem) >= 3 and stem in self._names:
                return self._names[stem]
        return None

    def city_name(self, code):
        self._reference()
        return self._cities.get(code, {}).get("city", code)

    # ---------- mapping ----------

    def _record(self, t):
        self._reference()
        dep = datetime.fromisoformat(t["departure_at"])
        minutes = int(t.get("duration_to") or t.get("duration") or 0)
        arrival = dep + timedelta(minutes=minutes)
        tz = self._cities.get(t["destination"], {}).get("tz")
        try:
            arrival = arrival.astimezone(ZoneInfo(tz)) if tz else arrival
        except Exception:  # unknown zone name: keep the departure offset
            pass
        number = f"{t['airline']}{t.get('flight_number', '')}"
        code_o, code_d = t.get("origin_airport") or t["origin"], t.get("destination_airport") or t["destination"]
        return {
            "id": f"{number}-{dep:%Y%m%d%H%M}",
            "airline": self._airlines.get(t["airline"], t["airline"]),
            "flight_number": number,
            "origin": {"code": code_o, "city": self.city_name(t["origin"])},
            "destination": {"code": code_d, "city": self.city_name(t["destination"])},
            "departure_local": dep.strftime("%Y-%m-%dT%H:%M"),
            "arrival_local": arrival.strftime("%Y-%m-%dT%H:%M"),
            "duration_min": minutes,
            "stops": int(t.get("transfers") or 0),
            "via": None,
            "price_azn": round(float(t["price"]) * config.USD_TO_AZN, 2),
            "cabin": "economy",
            "baggage_kg": None,
            "seats_available": None,
            "url": "https://www.aviasales.com" + t["link"] if t.get("link") else "https://www.aviasales.com",
        }

    # ---------- repository interface (same as the mock FlightRepository) ----------

    def all(self):
        return list(self._items.values())

    def get(self, flight_id):
        return self._items.get(flight_id)

    def search(self, origin=None, destination=None, date=None):
        if not origin:
            return []  # the API needs an origin; the Flights module defaults it to Baku
        params = {"origin": CITY_CODES.get(origin, origin), "currency": "usd", "sorting": "price",
                  "one_way": "true", "limit": PAGE_SIZE}
        if destination:
            params["destination"] = CITY_CODES.get(destination, destination)
        if date:
            params["departure_at"] = date
        found = []
        for page in range(1, MAX_PAGES + 1):
            body = self.api.get_json("/aviasales/v3/prices_for_dates", {**params, "page": page}, ttl=900)
            if not isinstance(body, dict) or not body.get("success", True):
                raise DataSourceError("aviasales: unexpected response")
            rows = body.get("data") or []
            for row in rows:
                try:
                    found.append(self._record(row))
                except (KeyError, ValueError, TypeError):
                    log.warning("skipped malformed ticket: %s", row)
            if len(rows) < PAGE_SIZE:
                break
        if date:
            found = [f for f in found if f["departure_local"].startswith(date)]
        unique = {}
        for f in found:
            unique.setdefault(f["id"], f)
        self._items.update(unique)
        return list(unique.values())

    def reserve(self, flight_id, passengers=1):
        f = self.get(flight_id)
        if f is None:
            return None
        booking = {"ref": f"FL{len(self.reservations) + 1:04d}", "flight": f, "passengers": passengers,
                   "url": f["url"]}
        self.reservations.append(booking)
        return booking

