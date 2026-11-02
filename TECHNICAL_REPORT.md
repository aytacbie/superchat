# SuperChat: technical report

One chat for flights (Aviasales), shopping (Shopping Assistant) and cinema (CinemaPlus). It runs on the official mock dataset by default, with no internet needed. Phase 2 is already connected: setting `SUPERCHAT_DATA=live` switches all three domains to real APIs behind the same interfaces.

## 1. Architecture

```
Browser (static/index.html) ── POST /api/chat {message, session_id}
FastAPI (app/main.py) ── session store (in memory, one dict per session_id)
   ├─ nlp.py        language detection, normalisation, dates, counts, references
   ├─ router.py     message → category + domain module(s)
   ├─ flights.py · shopping.py · cinema.py    read session state, call a repository, write the reply
   ├─ repositories.py   mock FlightRepository · ProductRepository · ShowtimeRepository (data/*.json)
   └─ sources/          live repositories with the same methods (Phase 2), on top of apiclient.py
```

The pipeline for each message has four steps:
1. Detect the language and normalise the text: lower-case it and fold Azerbaijani letters, so "Bakı" matches "baki".
2. Classify the message (section 2).
3. Call one module, or several for a mixed request.
4. Join the replies.

The UI shows which domain answered each reply. Everything is Python 3 with FastAPI. No language model is used. One command starts the app: `uvicorn app.main:app`.

## 2. Routing method

**Approach: rules with keyword lists, plus session context.** Most keyword lists are generated from the data: product name stems in all three languages, brands, film titles, airlines, flight numbers and cities. Hand-written lists cover generic words ("flight", "uçuş", "рейс", "səbət", "корзина"…). Decision order in `router.classify`:

1. **Domain hits.** Two or more domains match → **mixed**: all matching modules answer, in one reply. One domain matches → that domain. If it is already the active domain and the message holds a reference ("the cheaper one", "it", "what about…"), the category is **follow-up**.
2. **No domain hit, but follow-up signals** (an ordinal, "it", "book", "seats", a date, a time of day, "sort", "compare"):
   - With an active domain → **follow-up**, resolved against that domain's last results.
   - Without one → **ambiguous**: one short clarifying question.
   - "Book it" with both a flight and a film on the table → "flight or cinema tickets?". The request is remembered and completed after the answer.
3. **A wish to buy** ("mənə … lazımdır", "I need", "купить") with no known product word → **shopping**, which says the item is not in the catalogue.
4. **Out-of-scope topics** (weather, hotel, taxi…) override weak flight evidence, so "hotel in Istanbul" is not a flight search. Anything else unmatched gets a polite refusal listing what SuperChat can do. Greetings get a short help text.

| Rules (chosen) | LLM function calling |
|---|---|
| ✅ Deterministic; every decision can be traced and explained | ❌ Non-deterministic, harder to test |
| ✅ Replies are built only from repository data; nothing is invented | ⚠️ Needs guardrails against invented flights and prices |
| ✅ Instant, free, works offline | ❌ Latency, cost, key and network needed |
| ❌ Only understands phrasings in its vocabulary | ✅ Understands paraphrases and typos |

The router is one function, `classify(text, session) → (category, domains)`. An LLM classifier, or a hybrid that calls an LLM only when the rules are unsure, could replace it without changing the modules.

## 3. State handling

Each session is a dict keyed by `session_id`; the browser keeps the id in `sessionStorage`.
- **Shared state:**
  - `lang`: detected per message; very short messages keep the previous language.
  - `active`: the last domain.
  - `prefs.party`: "we are 3 people" sizes later flight *and* cinema bookings.
  - `pending`: a booking that waits for "flight or cinema?".
- **Per-domain state:**
  - Flights: the last search, the results and the selected flight.
  - Shopping: the results, the selected product and the cart.
  - Cinema: the shown showtimes, the selected showtime and the current film or genre, so "and for Saturday?" keeps the film.
- **Returning to a topic.** Switching domain never clears another domain's state. "Back to the headphones" finds the earlier list again, and the cart lasts the whole session.
- **References.** `nlp.pick` maps "the second one", "the cheaper one", "the last one", "the 14:20 one" and distinctive names ("the Pro", "CA101") onto the list the user last saw in that domain.
- **Dates.** Mock data resolves dates against its reference day, Monday 2 November 2026; live data uses today in Baku (UTC+4). Supported forms include "tonight", "Friday", "6 November", "06.11", "cümə" and "в субботу".

## 4. Data layer design

Modules reach data only through repositories, whose field names follow Appendix A exactly:
- `FlightRepository`: `all()`, `get(id)`, `search(origin, destination, date)`, `reserve(id, passengers)`
- `ProductRepository`: `all()`, `get(id)`
- `ShowtimeRepository`: `movies`, `cinemas`, `movie(id)`, `cinema(id)`, `get(id)`, `search(movie_id, date)`, `reserve(id, seats)`

Reservations are mock: they hold seats in memory and return a booking reference. No payment or personal data is involved.

**Phase 2.** The organisers have not yet provided the official APIs, so Phase 2 was built against the closest free real sources. `app/sources/` holds live repositories with the same methods and fields, so the modules needed only small changes, for example for fields a source does not report. `sources.build()` picks one source per domain at start-up. It falls back to mock data when a source is not configured or does not answer. `GET /api/health` shows the choice.

| Domain | Live source | Key | Real data |
|---|---|---|---|
| Cinema | cinemaplus.az: the schedule, seat-map and film-page endpoints its own website uses | none | films, showtimes in 8 branches, hall, language, price, free seats, genre, runtime |
| Flights | Aviasales Data API `prices_for_dates`; Travelpayouts cities, airports, airlines | free token | airline, flight number, times, stops, price; any city in EN/RU/AZ |
| Shopping | DummyJSON product API, standing in for the Shopping Assistant backend (not yet provided) | none | 190+ products in 24 categories: brand, price, rating, stock, description |

- **CinemaPlus mapping.** Azerbaijani titles become aliases, so "Odisseya" finds "The Odyssey". Film details and free seats are loaded lazily and in parallel, only for the showtimes about to be shown. A seat-map status of 1 counts as free.
- **Aviasales mapping.**
  - **Cities.** Same-name cities resolve to the one with the most airports, so London means London UK. Azerbaijani endings are removed first ("Londona").
  - **Dates.** Without a date, the current and next month are asked.
  - **Prices and times.** USD prices are converted at the official 1.70 peg. Arrival times are local to the destination.
  - **Missing fields.** The API reports no baggage or seats left, so replies leave them out rather than invent them.
- **DummyJSON mapping.** The catalogue is read page by page and kept for an hour. Its own search endpoint answers free text that no catalogue word matched. Prices are converted from USD. Colour is read from the title, since the API has none. A model that does not exist, such as "iphone18", gets "'iphone 18' is not in our catalogue" and the closest products, with the same model line first. Visual search maps photo classes to title words ("airpods", "macbook").
- **Booking.** No public API sells tickets. SuperChat keeps the reference and links to CinemaPlus or Aviasales to buy.

**Phase 2 concerns, handled in `app/apiclient.py` for every source:**
- **Authentication:** headers or query parameters per client. Secrets come from `.env` and are never logged.
- **Rate limits:** a minimum gap between calls. `429` is retried and `Retry-After` is honoured.
- **Pagination:** `limit`/`page` until a short page arrives.
- **Latency:** 8 s timeouts and retries with backoff. Concurrent identical requests share one call, data loads in the background at start-up, and lists stop at 10 lines.
- **Caching:** a TTL per call, from 2 min for seat maps to 24 h for reference data.
- **Logging:** provider, path, status and latency for every call, plus counters in `/api/health`.
- **Failures:** a circuit breaker pauses a provider for 60 s after 3 failures in a row. The user gets "CinemaPlus is not responding, please try again" in their language, never a stack trace.

## 5. Quality and testing

- **No invented data.** Every flight, product, film, price and showtime comes from a repository record. When nothing matches, SuperChat says so and offers real alternatives: other dates, the destination list, the categories it sells.
- **Language and length.** Replies use Azerbaijani, English and Russian templates, chosen per message, with one line per result.
- **Routing tests.** `eval_routing.py` runs 49 conversations with 123 turns in EN, AZ and RU, including the brief's 8 samples, on the mock dataset. It checks the category and a fact in each reply: routing 123/123, answers 114/114.
- **Data layer tests.** `tests/test_sources.py` has 17 offline tests covering the client's cache, retries, 429, circuit breaker and request sharing, and the CinemaPlus, Aviasales and DummyJSON mappings. See `TEST_LOG.md` for details and the error analysis.

## 6. Bonus tasks

**Visual search (`app/visual.py`).** The catalogue has no photos, so search is zero-shot. CLIP text embeddings describe 10 catalogue classes and 14 "not sold here" classes. At runtime the int8 CLIP vision model (ONNX, 90 MB, CPU) embeds the photo, and a softmax gives a confidence per class:
- ≥ 60 % → show the products with the confidence, and "add it to my cart" works.
- 20–60 % → ask "A or B?".
- Lower, or a class we do not sell → ask the user to describe the item.

On 194 labelled photos, 94 % of catalogue products were identified confidently with none confidently wrong, and 91 % of other items were rejected. The limit: two products of the same type (the two laptops) cannot be told apart.

**Voice input.** The browser's Web Speech API runs hands-free. It detects the start and end of each utterance with no push-to-talk and sends the text through the same `/api/chat` pipeline. The recognition language follows the conversation (en-US, az-AZ, ru-RU). 🔊 reads replies aloud and pauses the microphone meanwhile. It does not work in Firefox, Chrome sends audio to Google, and Azerbaijani recognition is weaker.

**Multilingual.** The whole conversation works in AZ, EN and RU, including switching language mid-session.

## 7. Known limitations

- **Vocabulary-bound understanding.** Phrasings or typos outside the keyword lists may be routed as out of scope. This is the main cost of rules.
- **English data.** Synopses, descriptions and city names stay in English inside AZ/RU replies.
- **Unofficial cinema endpoints.** If cinemaplus.az changes, the cinema source fails politely, and switching to mock data needs a restart.
- **Test product catalogue.** DummyJSON is a real API, but its catalogue is sample data: English only, USD prices, older models. The real Shopping Assistant backend would replace only `sources/dummyjson.py`.
- **Cached flight prices.** The Data API returns recent cheapest fares (one per day), not a live search; prices can differ on Aviasales.
- **In-memory state.** Sessions, carts and bookings are lost on restart; several server instances would need a shared store such as Redis.
- **Other gaps.** One flight search per message, and no combined round-trip price.

## 8. Libraries and sources

- **Libraries:** FastAPI (MIT), Uvicorn (BSD-3), Pydantic (MIT), python-multipart (Apache-2.0), HTTPX (BSD-3), tzdata (Apache-2.0).
- **Visual search:** CLIP ViT-B/32 (OpenAI, MIT) as the ONNX export `Xenova/clip-vit-base-patch32`, with ONNX Runtime (MIT), NumPy (BSD-3), Pillow (MIT-CMU) and huggingface_hub (Apache-2.0).
- **Voice:** the browser's Web Speech API.
- **Data:** the organisers' mock dataset; cinemaplus.az; Aviasales Data API and Travelpayouts reference data (travelpayouts.com); DummyJSON (dummyjson.com). Visual test photos come from the author's earlier project.
