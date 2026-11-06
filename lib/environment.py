"""Load local defaults without replacing platform-provided configuration."""

import os
from pathlib import Path
from dotenv import load_dotenv


def load_local_environment(directory: Path) -> None:
    environment = os.getenv("APP_ENV", "local").strip().lower()
    if os.getenv("RENDER") or environment in {"production", "prod", "staging"}:
        return
    # Explicit process values win; local defaults take precedence over .env defaults.
    for name in (".env.local", ".env"):
        load_dotenv(directory / name, override=False)
