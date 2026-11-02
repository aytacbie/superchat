# SuperChat: technical report

One chat for flights (Aviasales), shopping (Shopping Assistant) and cinema (CinemaPlus). Phase 1, built on the official mock dataset.

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
   └─ repositories.py   FlightRepository · ProductRepository · ShowtimeRepository
                         (Phase 1: JSON files in data/; Phase 2: real APIs)
```

Each message goes through a fixed pipeline:
1. Detect the language and normalise the text. Lower-case it and fold Azerbaijani letters, so "Bakı" and "baki" match.
2. Classify the message (section 2).
3. Call one module, or several for a mixed request.
4. Join the replies.

The UI shows which domain answered each reply and highlights the active domain. The whole application is Python 3 with FastAPI. It needs no external services and no language model, so it runs fully offline against the mock data. One command starts it: `uvicorn app.main:app`.

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

**Phase 2 swap.** Replace each class with an API client that has the same methods. Authentication, pagination, rate limiting, caching and retries live inside the client. Product search and filtering now run in the module over `all()`; with a large real catalogue, `ProductRepository` gets a `search(...)` method that pushes filters to the backend.

**Errors.** Load errors raise `DataSourceError`. Any exception inside a module is caught in `main.py`, logged on the server and answered with a polite "something went wrong" in the user's language. Stack traces never reach the chat.

## 5. Quality rules

- **No invented data.** Every flight, product, film, price and showtime in a reply comes from a repository record. When nothing matches, SuperChat says so and offers real alternatives: dates with flights on that route, dates a film is showing, the list of destinations.
- **Language.** Replies use templates in Azerbaijani, English and Russian, chosen per message. Mixed-language queries work because the vocabulary of all three languages is checked on every message.
- **Concise.** One line per result, with details only on request.

## 6. Testing

`eval_routing.py` runs 45 scripted conversations (119 turns, EN, AZ and RU), including all 8 sample conversations from the brief. It checks both the routing category and a fact in each reply. Result: routing 119/119, answer checks 110/110. See `TEST_LOG.md` for the breakdown and error analysis.

## 7. Known limitations

- **Vocabulary-bound understanding.** Phrasings, synonyms or typos outside the keyword lists may be routed to out of scope or ambiguous. This is the main cost of the rule-based choice.
- **Data in English only.** The mock records (descriptions, synopses, colours, city names) are in English, so parts of an Azerbaijani or Russian reply stay in English. Product names are localised because the dataset provides them.
- **In-memory state.** Sessions, carts and mock bookings live in server memory and are lost on restart. With several server instances they would need a shared store such as Redis.
- **One intent per domain per message.** Two different flights in one message are treated as one search.
- **No real round-trip pricing.** Outbound and return flights are listed separately.
- **Bonus tasks** (voice input, visual search) are not implemented in Phase 1. Multilingual support (AZ/RU/EN, switching mid-session) is implemented as part of the core.

## 8. Libraries and sources

- FastAPI (MIT licence), Uvicorn (BSD-3), Pydantic (MIT), Python standard library.
- No language model, no external data provider.
- Mock dataset supplied by the organisers.
