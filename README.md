# SuperChat

One chat for flights ✈️, shopping 🛒 and cinema 🎬, built on the official mock dataset (reference date: Monday, 2 November 2026). It works in English, Azerbaijani and Russian.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app
```

Then open http://127.0.0.1:8000

## Routing tests

```bash
python eval_routing.py        # add -v to print every reply
```

Results and error analysis are in [TEST_LOG.md](TEST_LOG.md). Architecture, routing method, state handling and limitations are covered in [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md).

## Structure

- `app/repositories.py`: data layer (`FlightRepository`, `ProductRepository`, `ShowtimeRepository`). In Phase 2 these are swapped for real API clients that keep the same method signatures.
- `app/router.py`: a rule-based router. Each message is classified as flights, shopping, cinema, mixed, follow-up, ambiguous or out of scope.
- `app/flights.py`, `app/shopping.py`, `app/cinema.py`: the domain modules. Each one keeps its own state per session.
- `app/nlp.py`: language detection (AZ/EN/RU), dates relative to the reference day, counts, and references such as "the second one" or "the cheaper one".
- `app/main.py`: the FastAPI server (`POST /api/chat`, plus the chat page at `/`).
- `static/index.html`: the chat page.
- `data/`: the mock JSON files.

## Deploy (Render)

- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
