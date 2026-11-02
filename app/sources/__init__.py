"""Picks the data source for each domain: the real API when it is configured and reachable,
otherwise the official mock dataset (so the chat always works, also offline)."""
import logging
import threading

from .. import config, nlp
from ..repositories import DataSourceError, FlightRepository, ProductRepository, ShowtimeRepository

log = logging.getLogger("superchat.sources")


def build(mode=None):
    mode = mode or config.DATA_MODE
    repos = {"flights": FlightRepository(), "shopping": ProductRepository(), "cinema": ShowtimeRepository()}
    if mode != "live":
        return repos
    nlp.TODAY = nlp.baku_today()
    from .cinemaplus import CinemaPlusRepository
    from .dummyjson import DummyJsonRepository
    from .travelpayouts import TravelpayoutsRepository

    try:
        cinema = CinemaPlusRepository()
        cinema.search(date=nlp.TODAY.isoformat())  # today's schedule; fails fast if the site is down
        repos["cinema"] = cinema
        threading.Thread(target=cinema.preload, daemon=True).start()  # rest of the week, genres, runtimes
    except DataSourceError as e:
        log.warning("cinema: using mock data (%s)", e)
    try:
        shop = DummyJsonRepository()
        shop.all()  # the whole catalogue (four pages); fails fast if the API is down
        repos["shopping"] = shop
    except DataSourceError as e:
        log.warning("shopping: using mock data (%s)", e)
    try:
        repos["flights"] = TravelpayoutsRepository(config.TRAVELPAYOUTS_TOKEN)
    except DataSourceError as e:
        log.warning("flights: using mock data (%s)", e)
    for name, repo in repos.items():
        log.info("%s data source: %s", name, repo.source)
    return repos
