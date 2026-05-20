import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(
    dotenv_path=Path(__file__).resolve().parent.parent / ".env"
)


def _get_env(name: str) -> str | None:
    """Return a trimmed env var value, or None when unset/blank."""
    value = os.getenv(name)

    if value is None:
        return None

    value = value.strip()
    return value or None


# Top-level variables (for old imports)
YOUTUBE_API_KEY = _get_env("YOUTUBE_API_KEY")
GEMINI_API_KEY = _get_env("GEMINI_API_KEY")
GROQ_API_KEY = _get_env("GROQ_API_KEY")
SERPAPI_API_KEY = _get_env("SERPAPI_API_KEY")


# Settings object (for main.py)
class Settings:
    YOUTUBE_API_KEY = YOUTUBE_API_KEY
    GEMINI_API_KEY = GEMINI_API_KEY
    GROQ_API_KEY = GROQ_API_KEY
    SERPAPI_API_KEY = SERPAPI_API_KEY


settings = Settings()