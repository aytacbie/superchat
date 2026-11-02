"""Offline tests for the Phase 2 data layer: the HTTP client (cache, retries, rate limits,
circuit breaker) and the CinemaPlus and Aviasales mappings, using recorded response samples.

Run: python -m unittest discover tests"""
import os
import sys
import threading
from datetime import date
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SUPERCHAT_DATA", "mock")

from app import nlp  # noqa: E402
from app.apiclient import ApiClient  # noqa: E402
from app.repositories import DataSourceError  # noqa: E402
from app.sources.cinemaplus import CinemaPlusRepository  # noqa: E402
from app.sources.travelpayouts import TravelpayoutsRepository  # noqa: E402


def client(handler, **kw):
    kw = {"min_interval": 0, "backoff": 0, **kw}
    return ApiClient("test", "https://example.test", transport=httpx.MockTransport(handler), **kw)


class ApiClientTest(unittest.TestCase):
    def test_cache_hit_skips_second_call(self):
        calls = []
        api = client(lambda r: calls.append(r) or httpx.Response(200, json={"ok": 1}))
        self.assertEqual(api.get_json("/x", {"a": 1}), {"ok": 1})
        self.assertEqual(api.get_json("/x", {"a": 1}), {"ok": 1})
        self.assertEqual(len(calls), 1)
        self.assertEqual(api.stats["cache_hits"], 1)

    def test_retries_server_errors_then_succeeds(self):
        answers = iter([httpx.Response(503), httpx.Response(500), httpx.Response(200, json=[1])])
        api = client(lambda r: next(answers), retries=2)
        self.assertEqual(api.get_json("/x"), [1])

    def test_rate_limited_429_is_retried(self):
        answers = iter([httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={})])
        self.assertEqual(client(lambda r: next(answers)).get_json("/x"), {})

    def test_client_error_is_not_retried(self):
        calls = []
        api = client(lambda r: calls.append(r) or httpx.Response(401), retries=3)
        with self.assertRaises(DataSourceError):
            api.get_json("/x")
        self.assertEqual(len(calls), 1)

    def test_timeouts_raise_data_source_error(self):
        def boom(request):
            raise httpx.ConnectTimeout("slow", request=request)
        with self.assertRaises(DataSourceError):
            client(boom, retries=1).get_json("/x")

    def test_circuit_opens_after_repeated_failures(self):
        calls = []
        api = client(lambda r: calls.append(r) or httpx.Response(500), retries=0, breaker_threshold=2)
        for _ in range(2):
            with self.assertRaises(DataSourceError):
                api.get_json("/x", ttl=0)
        with self.assertRaises(DataSourceError):
            api.get_json("/y")
        self.assertEqual(len(calls), 2)  # the third call never reached the provider
        self.assertEqual(api.status()["circuit"], "open")

    def test_auth_params_are_sent(self):
        seen = []
        api = ApiClient("t", "https://example.test", params={"token": "abc"}, min_interval=0,
                        transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={})))
        api.get_json("/x", {"q": "1"})
        self.assertEqual(seen[0].url.params["token"], "abc")

    def test_concurrent_identical_requests_hit_the_provider_once(self):
        calls, gate = [], threading.Event()

        def slow(request):
            calls.append(request)
            gate.wait(1)
            return httpx.Response(200, json={})
        api = client(slow)
        threads = [threading.Thread(target=api.get_json, args=("/x",)) for _ in range(4)]
        for t in threads:
            t.start()
        gate.set()
        for t in threads:
            t.join()
        self.assertEqual(len(calls), 1)


ROW = '''<tr data-cinema="28Mall" data-date="04.11.2026" data-real-date="04.11.2026" data-language="1798">
  <td><a href="/{lang}/films/{slug}/">{title}</a></td>
  <td>{time}</td>
  <td><a href="/{lang}/cinema/about-cinemaplus/28-mall/">28 Mall</a></td>
  <td>Platinum</td>
  <td class="poster_icons3"><span><b></b>Movie language: Rus</span><span><b></b>Movie format: 2D</span></td>
  <td>20.00 AZN</td>
  <td><div class="zone_input" data-price="20.00" data-hall="Platinum" data-session="198455" data-repeater="4358992"
       data-cinema="28Mall" data-age="18" data-grup="baku"></div></td>
</tr>'''
FILM = '''<meta property="og:description" content="Odysseus sails home." />
<div><b>Duration</b> 190 minutes</div><div><b>Genre</b> Fantasy, Science fiction</div>
<div><b>Age restrictions</b> 18+</div>'''
HALL = {"places": [{"Status": "1"}, {"Status": "1"}, {"Status": "5"}, {"Status": "10"}]}


def cinemaplus_handler(request):
    path, lang = request.url.path, request.url.params.get("lang")
    if path == "/get_sessions_by_date.php":
        if request.url.params["datex"] != "04.11.2026":
            return httpx.Response(200, text="")
        if lang == "english":
            return httpx.Response(200, text=ROW.format(lang="en", slug="the-odyssey", title="The Odyssey", time="9:30"))
        return httpx.Response(200, text=ROW.format(lang="az", slug="odisseya", title="Odisseya", time="9:30"))
    if path == "/getHall.php":
        return httpx.Response(200, json=HALL)
    if path == "/en/films/the-odyssey/":
        return httpx.Response(200, text=FILM)
    return httpx.Response(404)


class CinemaPlusTest(unittest.TestCase):
    def setUp(self):
        nlp.TODAY = date(2026, 11, 2)
        self.repo = CinemaPlusRepository(client(cinemaplus_handler))

    def test_schedule_maps_to_mock_schema(self):
        [sh] = self.repo.search(date="2026-11-04")
        self.assertEqual((sh["time"], sh["hall"], sh["price_azn"], sh["language"]), ("09:30", "Platinum", 20.0, "Russian"))
        m = self.repo.movie(sh["movie_id"])
        self.assertEqual((m["title"], m["age_rating"], m["aliases"]), ("The Odyssey", "18+", ["odisseya"]))
        self.assertEqual(self.repo.cinema("28Mall")["name"], "CinemaPlus 28 Mall")

    def test_film_details_and_seats_load_lazily(self):
        [sh] = self.repo.search(date="2026-11-04")
        m = self.repo.movie(sh["movie_id"])
        self.assertEqual(m["genre"], ["fantasy", "sci-fi"])
        self.assertEqual(m["duration_min"], 190)
        self.assertEqual((sh["seats_total"], sh["seats_available"]), (4, 2))

    def test_reservation_holds_seats(self):
        [sh] = self.repo.search(date="2026-11-04")
        self.assertIsNone(self.repo.reserve(sh["id"], 3))
        booking = self.repo.reserve(sh["id"], 2)
        self.assertIn("cinemaplus.az/en/films/the-odyssey", booking["url"])
        self.assertEqual(sh["seats_available"], 0)


CITIES_EN = [{"code": "BAK", "name": "Baku", "time_zone": "Asia/Baku", "has_flightable_airport": True, "cases": {}},
             {"code": "PAR", "name": "Paris", "time_zone": "Europe/Paris", "has_flightable_airport": True, "cases": {}}]
CITIES_RU = [{"code": "BAK", "name": "Баку", "has_flightable_airport": True, "cases": {"vi": "в Баку"}},
             {"code": "PAR", "name": "Париж", "has_flightable_airport": True, "cases": {"vi": "в Париж", "ro": "Парижа"}}]
TICKET = {"origin": "BAK", "destination": "PAR", "origin_airport": "GYD", "destination_airport": "CDG",
          "price": 250, "airline": "J2", "flight_number": "79", "departure_at": "2026-11-06T07:30:00+04:00",
          "transfers": 0, "duration_to": 390, "link": "/search/GYD0611CDG1"}


def aviasales_handler(request):
    path = request.url.path
    if path == "/data/en/cities.json":
        return httpx.Response(200, json=CITIES_EN)
    if path == "/data/ru/cities.json":
        return httpx.Response(200, json=CITIES_RU)
    if path == "/data/en/airlines.json":
        return httpx.Response(200, json=[{"code": "J2", "name": "Azerbaijan Airlines"}])
    if path == "/aviasales/v3/prices_for_dates":
        assert request.headers["X-Access-Token"] == "t0ken"
        return httpx.Response(200, json={"success": True, "data": [TICKET], "currency": "usd"})
    return httpx.Response(404)


class TravelpayoutsTest(unittest.TestCase):
    def setUp(self):
        transport = httpx.MockTransport(aviasales_handler)
        api = ApiClient("aviasales", "https://api.travelpayouts.com", headers={"X-Access-Token": "t0ken"},
                        min_interval=0, transport=transport)
        data = ApiClient("data", "https://api.travelpayouts.com", min_interval=0, transport=transport)
        self.repo = TravelpayoutsRepository("t0ken", client=api, data_client=data)

    def test_ticket_maps_to_mock_schema(self):
        [f] = self.repo.search("GYD", "PAR", "2026-11-06")
        self.assertEqual(f["airline"], "Azerbaijan Airlines")
        self.assertEqual(f["flight_number"], "J279")
        self.assertEqual(f["price_azn"], 425.0)  # 250 USD at 1.70
        self.assertEqual(f["arrival_local"], "2026-11-06T11:00")  # 07:30 Baku + 6h30 = 14:00 Baku = 11:00 Paris
        self.assertIsNone(f["baggage_kg"])
        self.assertEqual(f["url"], "https://www.aviasales.com/search/GYD0611CDG1")

    def test_flights_module_on_live_data(self):
        from app import flights
        from app.main import new_session
        s = new_session()
        s["lang"] = "az"
        reply = flights.handle(nlp.fold("Cümə günü Bakıdan Parisə uçuş"), s, self.repo)
        self.assertIn("Azerbaijan Airlines J279", reply)
        self.assertIn("425.00 AZN", reply)
        self.assertNotIn("None", reply)  # no baggage or seat count is made up
        reply = flights.handle("bunu bron et", s, self.repo)
        self.assertIn("aviasales.com/search/GYD0611CDG1", reply)

    def test_city_names_in_three_languages(self):
        self.assertEqual(self.repo.resolve_city("Paris"), "PAR")
        self.assertEqual(self.repo.resolve_city("Parisə"), "PAR")
        self.assertEqual(self.repo.resolve_city("Парижа"), "PAR")
        self.assertIsNone(self.repo.resolve_city("Atlantis"))

    def test_missing_token_is_rejected(self):
        with self.assertRaises(DataSourceError):
            TravelpayoutsRepository("")


if __name__ == "__main__":
    unittest.main()
