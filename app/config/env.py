from pathlib import Path

from dotenv import load_dotenv

# Default .env location: project root (dragbizz-voice-ai/.env)
_DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def load_env(env_path: Path | str | None = None) -> None:
    """Load environment variables from the given path or the project default."""
    load_dotenv(dotenv_path=env_path or _DEFAULT_ENV_PATH, override=False)