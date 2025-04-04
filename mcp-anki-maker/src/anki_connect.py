import requests
import json
import logging
from typing import Any, Dict, List, Optional

from .config import ANKI_CONNECT_URL, logger

class AnkiConnectClient:
    """Client for interacting with the AnkiConnect addon."""

    def __init__(self, url: str = ANKI_CONNECT_URL, version: int = 6):
        self.url = url
        self.version = version
        self.logger = logger # Use shared logger

    def _invoke(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Sends a request to AnkiConnect."""
        payload = {"action": action, "version": self.version}
        if params is not None:
            payload["params"] = params

        self.logger.debug(f"Invoking AnkiConnect: action={action}, params={params}")
        try:
            response = requests.post(self.url, json=payload, timeout=30) # Added timeout
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"AnkiConnect request failed: {e}", exc_info=True)
            raise ConnectionError(f"Failed to connect to AnkiConnect at {self.url}. Is Anki running with AnkiConnect installed and enabled?") from e

        try:
            result = response.json()
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to decode AnkiConnect response: {response.text}", exc_info=True)
            raise ValueError("Invalid JSON response received from AnkiConnect.") from e

        self.logger.debug(f"AnkiConnect response: {result}")

        if "error" in result and result["error"] is not None:
            error_message = f"AnkiConnect error for action '{action}': {result['error']}"
            self.logger.error(error_message)
            # Specific error handling can be added here if needed
            if "duplicate" in str(result["error"]).lower():
                 raise ValueError(f"Duplicate note detected by Anki: {result['error']}")
            raise RuntimeError(error_message)

        if "result" not in result:
             raise ValueError("Invalid response format from AnkiConnect: 'result' field missing.")

        return result["result"]

    def add_note(self, deck_name: str, model_name: str, fields: Dict[str, str], tags: Optional[List[str]] = None) -> int:
        """Adds a new note to Anki."""
        note = {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields,
            "options": {
                "allowDuplicate": False, # Let Anki handle duplicates based on the first field usually
                "duplicateScope": "deck"
            },
            "tags": tags or []
        }
        try:
            note_id = self._invoke("addNote", {"note": note})
            if not isinstance(note_id, int):
                 self.logger.warning(f"addNote returned non-integer ID: {note_id}. Assuming success but check Anki.")
                 # Sometimes AnkiConnect might return null on success with duplicates disabled, treat as success?
                 # Or raise error? Let's raise for clarity.
                 if note_id is None: # Handle None case specifically if allowDuplicate=false might return it
                     raise ValueError("AnkiConnect returned null for addNote, possibly due to duplicate handling or misconfiguration.")
                 raise ValueError(f"AnkiConnect addNote returned unexpected type: {type(note_id)}")
            self.logger.info(f"Successfully added note for field '{fields.get('Word', 'N/A')}' with ID: {note_id}")
            return note_id
        except Exception as e:
            self.logger.error(f"Failed to add note for field '{fields.get('Word', 'N/A')}': {e}", exc_info=False) # Log less verbosely here
            raise # Re-raise the original exception

    def store_media_file(self, filename: str, data_base64: str) -> str:
        """Stores a media file (base64 encoded) in Anki's collection."""
        try:
            result = self._invoke("storeMediaFile", {"filename": filename, "data": data_base64})
            self.logger.info(f"Stored media file '{filename}' in Anki.")
            return str(result) # Should return filename on success
        except Exception as e:
            self.logger.error(f"Failed to store media file '{filename}': {e}", exc_info=True)
            raise

    def get_media_files_names(self, pattern: str = "*") -> List[str]:
        """Gets a list of media filenames matching a pattern."""
        try:
            filenames = self._invoke("getMediaFilesNames", {"pattern": pattern})
            if not isinstance(filenames, list):
                raise ValueError(f"AnkiConnect getMediaFilesNames returned unexpected type: {type(filenames)}")
            self.logger.debug(f"Retrieved {len(filenames)} media file names from Anki.")
            return filenames
        except Exception as e:
            self.logger.error(f"Failed to get media file names: {e}", exc_info=True)
            raise

