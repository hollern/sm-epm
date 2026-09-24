from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Explicit path: dotenv's default lookup switches to cwd under REPLs, notebooks and debuggers.
ENV_FILE = PROJECT_ROOT / '.env'


def load_env() -> None:
    load_dotenv(ENV_FILE)
