"""CinemaPlus live data: real films, showtimes, prices and free seats from cinemaplus.az.

CinemaPlus has no documented public API, so this reads the same public endpoints its own
website uses for the schedule (get_sessions_by_date.php), the seat map (getHall.php) and the
film pages. Records are mapped to the mock schema, so the Cinema module works unchanged.

Details that cost an extra request (genre, duration and synopsis from the film page; free
seats from the seat map) are loaded lazily the first time the module reads them."""
import html
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .. import nlp
from ..apiclient import ApiClient
from ..repositories import DataSourceError

log = logging.getLogger("superchat.cinemaplus")
BASE = "https://cinemaplus.az"
DAYS_AHEAD = 6  # the schedule is published a few days ahead; empty days cost one cached call
LANGUAGES = {"rus": "Russian", "aze": "Azerbaijani", "tur": "Turkish", "eng": "English"}
GENRE_NAMES = {"science fiction": "sci-fi", "sci fi": "sci-fi", "fantastic": "sci-fi", "animated": "animation",
               "cartoon": "animation", "romantic": "romance", "detective": "mystery", "musical": "music"}
# Names users type for each branch, keyed by the site's own cinema id.
ALIASES = {
    "GanjlikMall": ["ganjlik", "genclik", "гянджлик"],
    "28Mall": ["28 mall", "28mall"],
    "Sumgayit": ["sumgayit", "sumqayit", "сумгаит"],
    "AmburanMall": ["amburan", "амбуран"],
    "DenizMall": ["deniz mall", "deniz", "дениз"],
    "GanjaMall": ["ganja mall", "gence mall", "гянджа молл"],
    "Bakihanov": ["bakikhanov", "bakixanov", "бакиханов"],
    "AzerbaijanC.": ["azerbaijan cinema", "azerbaycan kinoteatri", "кинотеатр азербайджан"],
}
_ROW = re.compile(r"<tr data-cinema=.*?</tr>", re.S)


def _parallel(jobs):
    """Run (function, argument) pairs on a few threads; ApiClient still spaces the requests."""
    if jobs:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for future in [pool.submit(fn, arg) for fn, arg in jobs]:
                try:
                    future.result()
                except DataSourceError as e:
                    log.warning("CinemaPlus prefetch failed: %s", e)


class _Lazy(dict):
    """A record whose expensive fields are fetched on first access."""

    def __init__(self, loader, lazy_keys, **fields):
        super().__init__(**fields)
        self._loader = loader
        self._lazy_keys = lazy_keys

    def __missing__(self, key):
        if key not in self._lazy_keys:
            raise KeyError(key)
        self._loader(self)
        return dict.__getitem__(self, key)


def _attr(row, name):
    m = re.search(rf'data-{name}="([^"]*)"', row)
    return html.unescape(m.group(1)) if m else ""


class CinemaPlusRepository:
    source = "CinemaPlus (cinemaplus.az)"

    def __init__(self, client=None):
        self.api = client or ApiClient("cinemaplus", BASE, min_interval=0.1)
        self._movies, self._cinemas, self._showtimes = {}, {}, {}
        self._days = set()
        self._held = {}  # seats held by SuperChat bookings, per showtime
        self.reservations = []
        self._lock = threading.Lock()

    # ---------- schedule ----------

    def _load_day(self, day):
        """Fetch one day of the schedule (English titles plus Azerbaijani titles as aliases)."""
        if day in self._days:
            return
        datex = date.fromisoformat(day).strftime("%d.%m.%Y")
        page = self.api.get_text("/get_sessions_by_date.php", {"home": "yes", "lang": "english", "datex": datex},
                                 ttl=600)
        try:
            page_az = self.api.get_text("/get_sessions_by_date.php", {"home": "yes", "lang": "az", "datex": datex},
                                        ttl=600)
        except DataSourceError:
            page_az = ""
        az_titles = {}
        for row in _ROW.findall(page_az):
            m = re.search(r'/films/[^"]*">([^<]+)', row)
            if m:
                az_titles[_attr(row, "session") + _attr(row, "repeater")] = html.unescape(m.group(1)).strip()
        with self._lock:
            for row in _ROW.findall(page):
                self._add_row(row, day, az_titles)
            self._days.add(day)

    def _add_row(self, row, day, az_titles):
        film = re.search(r'<a href="/en/films/([^/"]+)/">([^<]+)</a>', row)
        cinema = re.search(r'<a href="(/en/cinema/[^"]+)">([^<]+)</a>', row)
        clock = re.search(r"<td>(\d{1,2}:\d{2})</td>", row)
        if not (film and cinema and clock):
            return
        slug, title = film.group(1), html.unescape(film.group(2)).strip()
        cid = _attr(row, "cinema")
        lang = re.search(r"Movie language: (\w+)", row)
        language = LANGUAGES.get(lang.group(1).lower(), lang.group(1)) if lang else "Unknown"
        age = _attr(row, "age")
        if slug not in self._movies:
            self._movies[slug] = _Lazy(self._load_film, {"genre", "duration_min", "synopsis"},
                                       id=slug, title=title, aliases=[], language=language,
                                       age_rating=f"{age}+" if age.isdigit() else "—", rating=None,
                                       url=f"{BASE}/en/films/{slug}/")
        movie = self._movies[slug]
        az = az_titles.get(_attr(row, "session") + _attr(row, "repeater"))
        if az and nlp.fold(az) != nlp.fold(title) and nlp.fold(az) not in movie["aliases"]:
            movie["aliases"].append(nlp.fold(az))
        if cid not in self._cinemas:
            self._cinemas[cid] = {"id": cid, "name": f"CinemaPlus {html.unescape(cinema.group(2)).strip()}",
                                  "district": _attr(row, "grup").title() or "—",
                                  "address": BASE + cinema.group(1), "aliases": ALIASES.get(cid, [])}
        sid = f"{_attr(row, 'session')}-{_attr(row, 'repeater')}"
        fmt = re.search(r"Movie format: (\w+)", row)
        self._showtimes[sid] = _Lazy(self._load_seats, {"seats_total", "seats_available"},
                                     id=sid, movie_id=slug, cinema_id=cid, date=day,
                                     time=f"{int(clock.group(1)[:-3]):02d}{clock.group(1)[-3:]}",
                                     hall=_attr(row, "hall"), language=language,
                                     format=fmt.group(1) if fmt else "",
                                     price_azn=float(_attr(row, "price") or 0),
                                     _hall=(cid, _attr(row, "session"), _attr(row, "price"), _attr(row, "repeater")))

    def _days_ahead(self):
        return [(nlp.TODAY + timedelta(days=i)).isoformat() for i in range(DAYS_AHEAD + 1)]

    def _ensure(self, day=None):
        for d in [day] if day else self._days_ahead():
            try:
                self._load_day(d)
            except DataSourceError:
                if day:  # the day the user asked about must load; others are best effort
                    raise
                log.warning("could not load CinemaPlus schedule for %s", d)

    # ---------- lazy details ----------

    def _load_film(self, movie):
        try:
            page = self.api.get_text(f"/en/films/{movie['id']}/", ttl=12 * 3600)
        except DataSourceError:
            page = ""
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
        genre = re.search(r"Genre ([^|]+?) (?:Age restrictions|Duration|Language|Director|Cast|Country)", text)
        minutes = re.search(r"Duration (\d+) minutes", text)
        desc = re.search(r'<meta property="og:description" content="([^"]*)"', page)
        genres = [g.strip().lower() for g in genre.group(1).split(",")] if genre else []
        movie.update(genre=[GENRE_NAMES.get(g, g) for g in genres],
                     duration_min=int(minutes.group(1)) if minutes else None,
                     synopsis=html.unescape(desc.group(1)).strip() if desc else "")

    def _load_seats(self, sh):
        cid, session, price, repeater = sh["_hall"]
        try:
            hall = self.api.get_json("/getHall.php", {"cinema": cid, "session_id": session, "price": price,
                                                     "repeater_id": repeater}, ttl=120)
            places = hall.get("places") or []
            free = sum(1 for p in places if str(p.get("Status")) == "1")
            sh.update(seats_total=len(places), seats_available=max(0, free - self._held.get(sh["id"], 0)))
        except (DataSourceError, AttributeError):
            sh.update(seats_total=None, seats_available=None)  # shown as "check on the website"

    def warm(self, showtimes):
        """Load seat maps and film details for the showtimes about to be shown, in parallel."""
        films = {sh["movie_id"]: self._movies[sh["movie_id"]] for sh in showtimes}
        jobs = [(self._load_seats, sh) for sh in showtimes if "seats_available" not in sh]
        jobs += [(self._load_film, m) for m in films.values() if "genre" not in m]
        _parallel(jobs)

    def preload(self):
        """Background warm-up: the rest of the week's schedule, then every film's details."""
        _parallel([(self._load_day, d) for d in self._days_ahead()])
        _parallel([(self._load_film, m) for m in list(self._movies.values()) if "genre" not in m])

    # ---------- repository interface (same as the mock ShowtimeRepository) ----------

    @property
    def movies(self):
        """Films known so far: today's schedule for sure, later days once preload() reaches them."""
        self._ensure(nlp.TODAY.isoformat())
        return list(self._movies.values())

    @property
    def cinemas(self):
        self._ensure(nlp.TODAY.isoformat())
        return list(self._cinemas.values())

    def movie(self, movie_id):
        return self._movies.get(movie_id)

    def cinema(self, cinema_id):
        return self._cinemas.get(cinema_id)

    def get(self, showtime_id):
        return self._showtimes.get(showtime_id)

    def search(self, movie_id=None, date=None):
        self._ensure(date)
        today = nlp.TODAY.isoformat()
        result = [s for s in self._showtimes.values()
                  if (not movie_id or s["movie_id"] == movie_id) and (s["date"] == date if date else s["date"] >= today)]
        return sorted(result, key=lambda s: (s["date"], s["time"]))

    def reserve(self, showtime_id, seats=1):
        """A booking held inside SuperChat; tickets are bought on cinemaplus.az (no payment here)."""
        s = self.get(showtime_id)
        if s is None:
            return None
        s.pop("seats_available", None)  # re-read the live seat map before booking
        if s["seats_available"] is not None and s["seats_available"] < seats:
            return None
        self._held[showtime_id] = self._held.get(showtime_id, 0) + seats
        if s["seats_available"] is not None:
            s["seats_available"] -= seats
        booking = {"ref": f"CN{len(self.reservations) + 1:04d}", "showtime": s, "seats": seats,
                   "url": self._movies[s["movie_id"]]["url"] + "#sessions"}
        self.reservations.append(booking)
        return booking
