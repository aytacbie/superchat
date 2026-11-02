# SuperChat

One chat for flights ✈️, shopping 🛒 and cinema 🎬, built on the official mock dataset (reference date: Monday, 2 November 2026).

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000

## Structure

- `app/repositories.py`: data layer (`FlightRepository`, `ProductRepository`, `ShowtimeRepository`). In Phase 2 these are swapped for real API clients that keep the same method signatures.
- `app/router.py`: a rule-based router. Each message is classified as flights, shopping, cinema, mixed, follow-up, ambiguous or out of scope.
- `app/flights.py`, `app/shopping.py`, `app/cinema.py`: the domain modules. Each one keeps its own state per session.
- `app/nlp.py`: language detection (AZ/EN/RU), dates relative to the reference day, counts, and references such as "the second one" or "the cheaper one".
- `app/main.py`: the FastAPI server (`POST /api/chat`, plus the chat page at `/`).
- `data/`: the mock JSON files.
