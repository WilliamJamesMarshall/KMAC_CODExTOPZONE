"""Load the repository's local .env without replacing process settings."""

from pathlib import Path

from dotenv import load_dotenv


def load_project_env(path: Path | None = None) -> bool:
    return load_dotenv(dotenv_path=path or Path.cwd() / ".env", override=False)
