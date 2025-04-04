# mcp-anki-maker/src/config.py

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# --- Project Paths ---
# __file__ is config.py inside src.
# parents[0] is src directory.
# parents[1] is the parent of src, which should be mcp-anki-maker.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --- Load .env from PROJECT_ROOT (mcp-anki-maker/.env) ---
dotenv_path = PROJECT_ROOT / '.env'
load_dotenv(dotenv_path=dotenv_path)
print(f"Attempting to load .env from: {dotenv_path}") # Add print for debugging
if not dotenv_path.exists():
    print(f"Warning: .env file not found at {dotenv_path}") # Add warning

# --- Core Configuration (Load AFTER loading .env) ---
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_API_BASE: str | None = os.environ.get("OPENAI_API_BASE") or None
ANKI_CONNECT_URL: str = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
ANKI_DECK_NAME: str = os.environ.get("ANKI_DECK_NAME", "Vocabulary")
ANKI_MODEL_NAME: str = os.environ.get("ANKI_MODEL_NAME", "Basic")

# --- Data and Log Paths (Relative to PROJECT_ROOT) ---
DATA_DIR = PROJECT_ROOT / "data"
AUDIO_DIR = DATA_DIR / "audio"
LOG_DIR = PROJECT_ROOT / "logs"

# --- Logging ---
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = LOG_DIR / "anki_mcp_py.log"

# --- Validation ---
if not OPENAI_API_KEY:
    # Raise error only if .env was expected but not found or key is missing
    if dotenv_path.exists():
         raise ValueError("Error: OPENAI_API_KEY not found in .env file or environment variables.")
    else:
         # If .env doesn't exist, maybe rely on system env vars, but warn loudly.
         print("Warning: OPENAI_API_KEY not found in environment variables and .env file was not found.")
         # Decide if you want to raise an error anyway or try to proceed. Raising is safer.
         raise ValueError("Error: OPENAI_API_KEY is required but not set.")


# --- Create directories if they don't exist ---
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- Basic Logging Setup ---
log_level_map = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

logging.basicConfig(
    level=log_level_map.get(LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("AnkiMCP")

logger.info("Configuration loaded.")
logger.info(f"Project Root: {PROJECT_ROOT}")
logger.info(f"Data Directory: {DATA_DIR}")
logger.info(f"Log Directory: {LOG_DIR}")
logger.info(f"Anki Deck: {ANKI_DECK_NAME}, Model: {ANKI_MODEL_NAME}")
logger.info(f"Audio Cache: {AUDIO_DIR}")
logger.info(f"Log File: {LOG_FILE}")

# Add a check after loading config
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is still not set after configuration load.")

