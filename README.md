# SuperChat

One chat for flights ✈️, shopping 🛒 and cinema 🎬. It works in English, Azerbaijani and Russian.

**Data (Phase 2):** cinema uses the real CinemaPlus schedule, prices and free seats from cinemaplus.az, with no key needed. Flights use real Aviasales prices through the free Travelpayouts Data API (token in `.env`). Shopping uses the official mock dataset for now. Any domain whose live source is not configured or not reachable falls back to the mock dataset (reference date: Monday, 2 November 2026). A green dot on a domain chip in the UI means live data.

Bonus features: **search by photo** (📎) and **hands-free voice input** (🎤, with optional spoken replies 🔊).

## Run locally

```bash
pip install -r requirements.txt
python scripts/download_model.py   # once: the 90 MB CLIP model for photo search
cp .env.example .env               # optional: add TRAVELPAYOUTS_TOKEN for real flights
uvicorn app.main:app
```

Then open http://127.0.0.1:8000. Voice input needs Chrome, Edge or Safari. `http://127.0.0.1:8000/api/health` shows which source each domain uses, with call, cache and error counters.

**Flights token (free):** sign up at [travelpayouts.com](https://www.travelpayouts.com), open *Profile → API token*, and put it in `.env` as `TRAVELPAYOUTS_TOKEN=...`. No payment is needed.

`SUPERCHAT_DATA=mock` forces the official dataset for every domain, for example to run the demo offline.

## Routing tests

```bash
python eval_routing.py                                 # routing on the mock dataset, add -v to print every reply
python -m unittest discover tests                      # data layer: HTTP client, CinemaPlus and Aviasales mapping (offline)
python eval_visual.py ../visual-search/data/images     # photo search, needs the photo folder
```

Results and error analysis are in [TEST_LOG.md](TEST_LOG.md). Architecture, routing method, state handling and limitations are covered in [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md).

## Structure

- `app/repositories.py`: mock data layer (`FlightRepository`, `ProductRepository`, `ShowtimeRepository`).
- `app/sources/`: live repositories with the same methods. `cinemaplus.py` reads cinemaplus.az; `travelpayouts.py` reads the Aviasales Data API. `__init__.py` picks live or mock per domain.
- `app/apiclient.py`: the shared HTTP client for Phase 2: auth, rate limiting, retries, caching, a circuit breaker and request logging.
- `app/config.py`: settings from the environment or `.env`.
- `app/router.py`: a rule-based router. Each message is classified as flights, shopping, cinema, mixed, follow-up, ambiguous or out of scope.
- `app/flights.py`, `app/shopping.py`, `app/cinema.py`: the domain modules. Each one keeps its own state per session.
- `app/nlp.py`: language detection (AZ/EN/RU), dates relative to the reference day, counts, and references such as "the second one" or "the cheaper one".
- `app/main.py`: the FastAPI server (`POST /api/chat`, `GET /api/health`, plus the chat page at `/`).
- `app/visual.py`: photo search (zero-shot CLIP with a confidence score). `scripts/build_visual_classes.py` rebuilds `data/visual_classes.json`.
- `static/index.html`: the chat page, including voice input.
- `data/`: the mock JSON files.

## Deploy (Render)

- Build: `pip install -r requirements.txt && python scripts/download_model.py`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
