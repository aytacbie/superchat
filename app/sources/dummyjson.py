"""Shopping live data from DummyJSON (dummyjson.com), a free public product API with no key.

The Shopping Assistant backend has not been provided by the organisers, so this open API
stands in for it: about 190 products in 24 categories, with brand, price (USD), rating,
stock and description. The catalogue is read page by page (limit/skip) and cached for an
hour; free-text requests also go to its search endpoint. Records are mapped to the mock
product schema, so the Shopping module works unchanged. Swapping in the real backend means
replacing only this file."""
import logging
import re
import time

from .. import config, nlp
from ..apiclient import ApiClient

log = logging.getLogger("superchat.dummyjson")
PAGE_SIZE = 50
FIELDS = "title,brand,category,price,rating,stock,description,tags"
# DummyJSON categories mapped onto the Shopping module's category names where one fits.
CATEGORIES = {"smartphones": "phones", "laptops": "computers",
              "mens-watches": "wearables", "womens-watches": "wearables", "womens-bags": "accessories",
              "mens-shoes": "sport", "womens-shoes": "sport", "sports-accessories": "sport",
              "kitchen-accessories": "home", "home-decoration": "home", "furniture": "home"}
COLORS = ["black", "white", "silver", "grey", "gray", "blue", "red", "green", "gold", "pink", "purple", "brown"]
# Photo classes of the visual search, matched by words in product titles.
VISUAL = {"headphones": ["headphone"], "earbuds": ["airpods", "earphone", "earbud"],
          "laptop": ["laptop", "macbook", "notebook"], "smartphone": ["iphone", "galaxy", "oppo", "realme", "vivo"],
          "smartwatch": ["watch series", "smartwatch", "smart watch"], "speaker": ["homepod", "echo", "speaker"],
          "running_shoes": ["sneaker", "running", "trainer"], "backpack": ["backpack"],
          "coffee_machine": ["coffee"], "board_game": ["board game"]}
# Title words too common to route a message to Shopping on their own ("check", "date", "family").
_COMMON = {"black", "white", "green", "brown", "silver", "purple", "classic", "check", "family", "photo", "frame",
           "plant", "house", "sports", "master", "night", "water", "juice", "short", "sleeve", "series", "cover",
           "table", "chair", "glass", "bottle", "cream", "fresh", "light", "smart", "apple", "plain", "small",
           "large", "women", "womens", "men's", "round", "steel", "wooden", "kitchen", "cooking", "dinner"}


def _color(p):
    text = nlp.fold(" ".join([p.get("title", ""), " ".join(p.get("tags") or [])]))
    color = next((c for c in COLORS if re.search(rf"\b{c}\b", text)), None)
    return "grey" if color == "gray" else color


def _record(p):
    title = p["title"].strip()
    return {
        "id": f"DJ{p['id']}",
        "name": {"en": title, "az": title, "ru": title},  # the API is English only
        "category": CATEGORIES.get(p.get("category"), p.get("category") or "other"),
        "brand": p.get("brand") or "—",
        "price_azn": round(float(p["price"]) * config.USD_TO_AZN, 2),
        "rating": round(float(p.get("rating") or 0), 1),
        "stock": int(p.get("stock") or 0),
        "color": _color(p),
        "description": p.get("description") or "",
    }


class DummyJsonRepository:
    source = "DummyJSON (dummyjson.com)"

    def __init__(self, client=None):
        self.api = client or ApiClient("dummyjson", "https://dummyjson.com", min_interval=0.1)
        self._items, self._loaded = {}, 0.0

    def all(self):
        """The whole catalogue, read page by page and kept for an hour."""
        if not self._items or time.monotonic() - self._loaded > 3600:
            items, skip = {}, 0
            while True:
                body = self.api.get_json("/products", {"limit": PAGE_SIZE, "skip": skip, "select": FIELDS}, ttl=0)
                page = body.get("products") or []
                items.update((r["id"], r) for r in map(_record, page))
                skip += len(page)
                if not page or skip >= body.get("total", 0):
                    break
            self._items, self._loaded = items, time.monotonic()
        return list(self._items.values())

    def get(self, product_id):
        if not self._items:
            self.all()
        return self._items.get(product_id)

    def search_text(self, query):
        """Free text through the API's own search, for requests no catalogue word matched."""
        body = self.api.get_json("/products/search", {"q": query, "limit": 20, "select": FIELDS}, ttl=600)
        found = [_record(p) for p in body.get("products") or []]
        self._items.update((p["id"], p) for p in found)
        return found

    def keywords(self):
        """Routing words: brands and distinctive title words."""
        words = {nlp.fold(p["brand"]) for p in self.all() if len(p["brand"]) >= 3}
        for p in self.all():
            words |= {w for w in re.findall(r"[a-z][a-z']{4,}", nlp.fold(p["name"]["en"])) if w not in _COMMON}
        return sorted(words)

    def visual_matches(self, label):
        keys = VISUAL.get(label, [])
        return [p["id"] for p in self.all() if any(k in nlp.fold(p["name"]["en"]) for k in keys)]
