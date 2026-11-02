# SuperChat: technical report

One chat for flights (Aviasales), shopping (Shopping Assistant) and cinema (CinemaPlus). Phase 1 was built on the official mock dataset. Phase 2 connects free real data sources: CinemaPlus's live schedule and the Aviasales Data API. The mock dataset stays as the offline fallback and as the routing test bed.

## 1. Architecture

```
Browser (static/index.html)
   │  POST /api/chat {message, session_id}
   ▼
FastAPI (app/main.py) ── session store (in memory, one dict per session_id)
   │
   ├─ nlp.py      language detection, normalisation, dates, counts, references
   ├─ router.py   message → category + domain module(s)
   │
   ├─ flights.py  ─┐
   ├─ shopping.py ─┼─ domain modules: read the session state, call a repository, write the reply
   ├─ cinema.py   ─┘
   │
   ├─ repositories.py   mock FlightRepository · ProductRepository · ShowtimeRepository (data/*.json)
   └─ sources/          live repositories with the same methods, chosen per domain at start-up
        ├─ cinemaplus.py      CinemaPlus schedule, seat maps, film pages (cinemaplus.az)
        ├─ travelpayouts.py   Aviasales Data API (prices) + Travelpayouts reference data
        └─ ../apiclient.py    shared HTTP client: auth, rate limit, retries, cache, circuit breaker, logs
```

Each message goes through a fixed pipeline:
1. Detect the language and normalise the text. Lower-case it and fold Azerbaijani letters, so "Bakı" and "baki" match.
2. Classify the message (section 2).
3. Call one module, or several for a mixed request.
4. Join the replies.

The UI shows which domain answered each reply and highlights the active domain; a green dot on a domain marks live data. The whole application is Python 3 with FastAPI and uses no language model. With `SUPERCHAT_DATA=mock`, or with no network, it runs fully offline against the mock data. One command starts it: `uvicorn app.main:app`.

## 2. Routing method

**Approach: rules with keyword lists, plus session context.** Most keyword lists are generated from the data itself: product name stems in all three languages, brands, film titles, airlines, flight numbers and cities. Hand-written lists cover generic words ("flight", "uçuş", "рейс", "film", "səbət", "корзина"…).

Decision order in `router.classify`:

1. **Domain hits.** Count which domains' keywords appear.
   - Two or more domains match → **mixed**. All matching modules are called and their replies are joined into one answer.
   - Exactly one domain matches → that domain. If it is the domain already active and the message contains a reference ("the cheaper one", "it", "only direct ones", "what about…"), it is labelled **follow-up**.
2. **No domain hit, but follow-up signals** (ordinals, "it/that", "book", "seats", a date, a time of day, "sort", "compare"):
   - If an active domain exists → **follow-up**, resolved inside that domain against its last results.
   - If no domain is active → **ambiguous**, and the system asks one short clarifying question.
   - "Book it" when both a flight and a film are on the table → **ambiguous** ("flight or cinema tickets?"). The request is remembered and completed after the answer.
3. **Out-of-scope topics** (weather, hotel, taxi…) override weak flight evidence. "Hotel in Istanbul" is not a flight search. Anything else unmatched is **out of scope** and gets a polite refusal that lists what SuperChat can do. Greetings and thanks get a short help text.

**Why rules, and the trade-offs.**

| Rules (chosen) | LLM function calling |
|---|---|
| ✅ Deterministic. Every decision can be traced to a keyword and explained in the demo | ❌ Non-deterministic, harder to test |
| ✅ Cannot hallucinate: replies are built only from repository data | ⚠️ Needs guardrails against invented flights and prices |
| ✅ Instant, free, works offline | ❌ Latency, cost, needs a key and network access |
| ❌ Only understands phrasings that are in the vocabulary | ✅ Understands free paraphrases and typos |
| ❌ Every new phrasing or language needs list maintenance | ✅ Scales to new phrasings and languages |

The router interface is a single function, `classify(text, session) → (category, domains)`. It could later be replaced by an LLM classifier, or by a hybrid that tries rules first and calls an LLM only when the result is ambiguous. The modules would not change.

## 3. State handling

Every session is a dict keyed by a `session_id`. The browser keeps the id in `sessionStorage`.

- **Shared state:** `lang` (detected per message; very short messages keep the previous language), `active` (last domain), `prefs.party` ("we are 3 people" sizes later flight *and* cinema bookings), and `pending` (a booking request waiting for "flight or cinema?").
- **Per-domain state:**
  - Flights: last search (origin, destination, date), result list, selected flight.
  - Shopping: result list, selected product, cart (product → quantity).
  - Cinema: shown showtimes, selected showtime, current focus (film or genre, so "and for Saturday?" keeps the film).
- **Returning to a topic.** Switching domain never clears another domain's state. "Back to the flights" shows the selected flight, or the earlier result list. "Back to the headphones" finds them again. The cart persists for the whole session.
- **Reference resolution** (`nlp.pick`) maps "the second one", "the cheaper one", "the last one", "the 14:20 one" and distinctive names ("the Pro", "CA101") onto the list the user last saw in that domain.
- **Dates** resolve against the dataset reference date, Monday 2 November 2026. "Tonight", "tomorrow", "Friday", "6 November", "06.11", "cümə", "в субботу" are all supported.

## 4. Data layer design

`app/repositories.py` is the only code that touches data. Each repository has a small interface:

- `FlightRepository`: `all()`, `get(id)`, `search(origin, destination, date)`, `reserve(id, passengers)`
- `ProductRepository`: `all()`, `get(id)`
- `ShowtimeRepository`: `movies`, `cinemas`, `movie(id)`, `cinema(id)`, `get(id)`, `search(movie_id, date)`, `reserve(id, seats)`

Field names follow Appendix A exactly. Reservations are mock: they lower `seats_available` in memory and return a booking reference. No payment and no personal data are involved.

**Phase 2: real data.** `app/sources/` holds live repositories with the same methods and field names, so the domain modules did not need a rewrite. `sources.build()` picks one source per domain at start-up. It uses the real API when that API is configured and answers, and the mock dataset otherwise. `GET /api/health` reports the choice.

| Domain | Live source | Key | What is real |
|---|---|---|---|
| Cinema | cinemaplus.az: the schedule, seat-map and film-page endpoints its own website uses | none | films, showtimes in all 8 branches, halls, language, format, price, free seats, genre, runtime, synopsis |
| Flights | Aviasales Data API `/aviasales/v3/prices_for_dates` + Travelpayouts `cities.json`, `airlines.json` | free token (`TRAVELPAYOUTS_TOKEN`) | airline, flight number, times, duration, stops, price; any city in EN/RU/AZ spelling |
| Shopping | mock dataset (the real catalogue API is still to be chosen) | — | — |

Mapping notes:
- **CinemaPlus.** Each schedule row becomes a showtime. Azerbaijani titles from the same session ids become aliases, so "Odisseya" finds "The Odyssey". Genre, runtime and synopsis come from the film page. Free seats come from the seat map, counting the seats with status 1 as free. Both are loaded lazily: only for the showtimes about to be shown, and in parallel.
- **Aviasales.** USD prices are converted at the official 1.70 peg. Arrival is turned into local time with the destination's time zone. The Data API has no baggage or seats-left fields, so they are `None` and the reply leaves them out rather than inventing them.
- **Booking.** No public API sells tickets, so SuperChat keeps a booking reference, holds the seats in memory, and links to the CinemaPlus film page or the Aviasales search to buy. No payment is taken.

**Phase 2 concerns (in `app/apiclient.py`, shared by every source):**
- **Authentication.** Per-client headers or query parameters, here the `X-Access-Token` header. Secrets come from the environment or `.env` and are never logged.
- **Rate limits.** A minimum gap between calls to each provider (0.1–0.3 s). `429` responses are retried and `Retry-After` is honoured.
- **Pagination.** Aviasales results are read page by page (`limit`/`page`) until a short page arrives.
- **Latency.** 8 s timeouts and two retries with exponential backoff. The site's own data loads in a background thread at start-up. Concurrent identical requests wait for the first one instead of repeating it. Long result lists stop at 10 lines.
- **Caching.** An in-memory TTL per call: 10 min for schedules, 2 min for seat maps, 12 h for film pages, 15 min for prices, 24 h for reference data.
- **Logging.** One line per call with provider, path, status and latency. `/api/health` adds call, cache-hit and error counters.
- **Failure handling.** A circuit breaker skips a provider for 60 s after 3 failures in a row. A failed call becomes `DataSourceError`, which the chat answers with "CinemaPlus is not responding right now, please try again" in the user's language. Stack traces never reach the chat.

**Live dates.** With live data, "today", "tonight" and "Friday" resolve against the current date in Baku (UTC+4), not the dataset's reference date.

## 5. Quality rules

- **No invented data.** Every flight, product, film, price and showtime in a reply comes from a repository record. When nothing matches, SuperChat says so and offers real alternatives: dates with flights on that route, dates a film is showing, the list of destinations.
- **Language.** Replies use templates in Azerbaijani, English and Russian, chosen per message. Mixed-language queries work because the vocabulary of all three languages is checked on every message.
- **Concise.** One line per result, with details only on request.

## 6. Testing

`eval_routing.py` runs 45 scripted conversations (119 turns, EN, AZ and RU), including all 8 sample conversations from the brief. It checks both the routing category and a fact in each reply. Result: routing 119/119, answer checks 110/110. See `TEST_LOG.md` for the breakdown and error analysis.

## 7. Bonus tasks

**Visual search (`app/visual.py`, `POST /api/image`).** The mock catalogue has no product photos, so visual search is zero-shot:
- **Offline step.** `scripts/build_visual_classes.py` embeds short text descriptions with the CLIP text model, for example "over-ear wireless headphones" or "a coffee maker". It covers 10 classes that map to catalogue products and 14 "not in catalogue" classes (food, furniture, tablets, analog watches…). The result is saved to `data/visual_classes.json`.
- **At runtime.** The int8 CLIP vision model (ONNX, about 90 MB, one CPU thread) embeds the photo. A softmax over cosine similarities (CLIP scale 100) gives a confidence per class.
  - Confidence ≥ 60 % → show the matching products with the confidence. They become the shopping results, so "add it to my cart" works. The user can also type or say a question together with the photo; it is answered right after the photo's result.
  - Confidence of 20–60 % → ask "Is it A (x %) or B (y %)?".
  - Lower, or the best class is something we do not sell → say so and ask the user to describe the item.
- **Results.** On 194 labelled photos: 94 % of catalogue products are identified confidently and none are confidently wrong; 91 % of other items are rejected (see `TEST_LOG.md`).
- **Trade-off.** Text prompts instead of real catalogue photos means no fine-grained matching. The two laptops, or the two phones, cannot be told apart from a photo. With real product images in Phase 2, the same embedder can index them (FAISS) for nearest-neighbour search.

**Voice input (`static/index.html`).**
- **Recognition.** The browser's Web Speech API transcribes speech. One tap on 🎤 turns hands-free mode on, with no push-to-talk. The recogniser detects the start and end of each utterance, and each utterance is sent to `/api/chat`, the same routing pipeline as typed text. Listening restarts after every reply.
- **Language.** The recognition language (en-US, az-AZ or ru-RU) follows the language the server detects for the conversation. It can also be switched by hand.
- **Spoken replies.** 🔊 turns on spoken replies (`speechSynthesis`). The microphone pauses while the reply is read aloud, so the assistant does not transcribe itself.
- **Limitations.** Recognition quality and privacy depend on the browser vendor's speech service, since Chrome sends audio to Google. It does not work in Firefox. Azerbaijani recognition is weaker than English or Russian.

**Multilingual.** Azerbaijani, English and Russian work across all domains, including switching language mid-session (section 5).

## 8. Known limitations

- **Vocabulary-bound understanding.** Phrasings, synonyms or typos outside the keyword lists may be routed to out of scope or ambiguous. This is the main cost of the rule-based choice.
- **Data in English only.** The mock records (descriptions, synopses, colours, city names) are in English, so parts of an Azerbaijani or Russian reply stay in English. Product names are localised because the dataset provides them.
- **Unofficial cinema endpoints.** CinemaPlus publishes no API. If its website changes, the cinema source fails and the chat says CinemaPlus is not responding; switching to mock data needs a restart. The "status 1 = free" reading of the seat map is inferred from the site's behaviour.
- **Cached flight prices.** The Aviasales Data API returns prices other users found recently, not a live search. A date nobody searched may show no flights, and prices can differ on Aviasales.
- **Shopping still on mock data**, until the real catalogue API is chosen.
- **In-memory state.** Sessions, carts and mock bookings live in server memory and are lost on restart. With several server instances they would need a shared store such as Redis.
- **One intent per domain per message.** Two different flights in one message are treated as one search.
- **No real round-trip pricing.** Outbound and return flights are listed separately.
- **Visual search cannot tell two products of the same type apart**, such as the two laptops, because there are no catalogue photos.

## 9. Libraries and sources

- FastAPI (MIT licence), Uvicorn (BSD-3), Pydantic (MIT), python-multipart (Apache-2.0), HTTPX (BSD-3), tzdata (Apache-2.0), Python standard library.
- Live data: cinemaplus.az (public website endpoints), Aviasales Data API and Travelpayouts reference data (free, travelpayouts.com).
- Visual search: CLIP ViT-B/32 (OpenAI, MIT) in the ONNX export `Xenova/clip-vit-base-patch32`; ONNX Runtime (MIT), NumPy (BSD-3), Pillow (MIT-CMU), huggingface_hub (Apache-2.0).
- Voice: the browser's Web Speech API and speechSynthesis. No extra library.
- No language model.
- Mock dataset supplied by the organisers. Visual test photos come from the author's earlier `visual-search` project.
