"""Data access layer. Phase 1 reads the mock JSON files; in Phase 2 these
classes are replaced by API clients with the same method signatures."""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class DataSourceError(Exception):
    pass


def _load(name):
    try:
        with open(DATA_DIR / name, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise DataSourceError(f"cannot load {name}") from e


class FlightRepository:
    def __init__(self):
        self._items = _load("flights.json")
        self.reservations = []

    def all(self):
        return list(self._items)

    def get(self, flight_id):
        return next((f for f in self._items if f["id"] == flight_id), None)

    def search(self, origin=None, destination=None, date=None):
        result = []
        for f in self._items:
            if origin and f["origin"]["code"] != origin:
                continue
            if destination and f["destination"]["code"] != destination:
                continue
            if date and not f["departure_local"].startswith(date):
                continue
            result.append(f)
        return result

    def reserve(self, flight_id, passengers=1):
        f = self.get(flight_id)
        if f is None or f["seats_available"] < passengers:
            return None
        f["seats_available"] -= passengers
        booking = {"ref": f"FL{len(self.reservations) + 1:04d}", "flight": f, "passengers": passengers}
        self.reservations.append(booking)
        return booking


class ProductRepository:
    def __init__(self):
        self._items = _load("products.json")

    def all(self):
        return list(self._items)

    def get(self, product_id):
        return next((p for p in self._items if p["id"] == product_id), None)


class ShowtimeRepository:
    def __init__(self):
        self.movies = _load("movies.json")
        self.cinemas = _load("cinemas.json")
        self._items = _load("showtimes.json")
        self.reservations = []

    def movie(self, movie_id):
        return next((m for m in self.movies if m["id"] == movie_id), None)

    def cinema(self, cinema_id):
        return next((c for c in self.cinemas if c["id"] == cinema_id), None)

    def get(self, showtime_id):
        return next((s for s in self._items if s["id"] == showtime_id), None)

    def search(self, movie_id=None, date=None):
        result = []
        for s in self._items:
            if movie_id and s["movie_id"] != movie_id:
                continue
            if date and s["date"] != date:
                continue
            result.append(s)
        return sorted(result, key=lambda s: (s["date"], s["time"]))

    def reserve(self, showtime_id, seats=1):
        s = self.get(showtime_id)
        if s is None or s["seats_available"] < seats:
            return None
        s["seats_available"] -= seats
        booking = {"ref": f"CN{len(self.reservations) + 1:04d}", "showtime": s, "seats": seats}
        self.reservations.append(booking)
        return booking
