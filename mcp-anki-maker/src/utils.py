import re
import hashlib
import logging
from typing import Optional, Tuple, List
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# --- Data Structures ---
class WordInput(BaseModel):
    word: str = Field(..., description="The word to add (English only)")
    definition: str = Field(..., description="The definition of the word (English only)")
    example: Optional[str] = Field(None, description="An example sentence using the word (English only)")
    # notes: Optional[str] = Field(None, description="Additional notes about the word (English only)")
    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the word (alphanumeric, hyphens, and underscores only)")

# --- Validation Functions ---
# Regex patterns (stricter than original TS to avoid potential issues)
# Allow letters, spaces, hyphens, apostrophes
WORD_PATTERN = re.compile(r"^[a-zA-Z\s'-]+$")
# Allow common text characters including punctuation
TEXT_PATTERN = re.compile(r"^[a-zA-Z0-9\s.,!?;:'\"()\[\]\-]*$")
# Allow letters, numbers, hyphens, underscores
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

def validate_word_data(word_data: WordInput) -> Tuple[bool, Optional[str]]:
    """Validates the word data fields (removed strict English checks)."""
    if word_data.tags:
        for tag in word_data.tags:
            if not TAG_PATTERN.match(tag):
                return False, f'Tag "{tag}" for word "{word_data.word}" contains invalid characters. Use only letters, numbers, hyphens, underscores.'
    return True, None


# --- Helper Functions ---
def format_word_for_filename(word: str) -> str:
    """Formats a word into a safe filename component."""
    # Replace non-alphanumeric characters with underscore
    s = re.sub(r'[^a-zA-Z0-9]', '_', word)
    # Replace multiple underscores with single underscore
    s = re.sub(r'_+', '_', s)
    # Remove leading/trailing underscores
    s = s.strip('_')
    return s.lower() or "invalid_word" # Ensure not empty

def get_stable_hash(text: str) -> str:
    """Generates a stable MD5 hash (8 chars) for the given text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]

