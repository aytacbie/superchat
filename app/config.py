"""Settings from environment variables, optionally loaded from a .env file in the project root.

SUPERCHAT_DATA        mock (default) or live. Mock is the official dataset and needs no internet
                      (brief, section 8). Live is Phase 2: the real APIs, falling back to the mock
                      dataset for a domain whose API is not configured or not reachable at start-up.
TRAVELPAYOUTS_TOKEN   Aviasales (Travelpayouts) Data API token; free at travelpayouts.com.
USD_TO_AZN            Exchange rate for prices quoted in USD (the manat is pegged at 1.70)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file():
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

DATA_MODE = os.environ.get("SUPERCHAT_DATA", "mock").lower()
TRAVELPAYOUTS_TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
USD_TO_AZN = float(os.environ.get("USD_TO_AZN", "1.70"))
