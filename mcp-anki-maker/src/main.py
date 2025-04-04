# src/main.py
import atexit
import sys
import csv # Import csv module
from typing import List, Dict, Any, Optional # Ensure Optional is imported
import logging
from pathlib import Path # Import Path

# Use Pydantic directly for input model definition
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from openai import OpenAI # Use synchronous client

from .config import (
    OPENAI_API_KEY, OPENAI_API_BASE, ANKI_DECK_NAME, ANKI_MODEL_NAME, logger,
    DATA_DIR # Import DATA_DIR
)
from .utils import WordInput, validate_word_data # WordInput is already a Pydantic model
from .anki_connect import AnkiConnectClient
from .audio_service import AudioService

# --- Initialization ---
logger.info("Initializing Anki MCP Python Server (Synchronous)...")

# Use Sync client
openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)

anki_client = AnkiConnectClient()
# Pass the sync openai client to AudioService
audio_service = AudioService(openai_client, anki_client)

mcp = FastMCP(
    name="anki-mcp-py-sync", # Renamed slightly
    version="1.0.0",
    description="Synchronous Python version of Anki MCP for adding vocabulary with audio and CSV backup.",
    logger=logger
)

# --- CSV Backup Configuration and Function ---
CSV_BACKUP_FILE = DATA_DIR / "anki_vocabulary_backup.csv"
# Define expected fields in Anki Notes and corresponding CSV headers
# !!! IMPORTANT: Adjust these keys ("Word", "Definition", etc.) to EXACTLY match your Anki Note Type fields !!!
ANKI_FIELD_MAP = {
    "Word": "word",
    "Definition": "definition",
    "Example": "example",
    # "Notes": "notes", # Assuming you have a 'Notes' field in Anki
    # Add other text fields from your Anki note type here if you want them backed up
    # e.g., "MyCustomField": "my_custom_field_header"
}
# Automatically create CSV headers based on the map + tags
CSV_HEADERS = list(ANKI_FIELD_MAP.values()) + ["tags"]

def backup_anki_deck_to_csv():
    """Fetches all notes from the configured Anki deck and saves them to a CSV file."""
    logger.info(f"Starting Anki deck backup to {CSV_BACKUP_FILE}...")
    try:
        # 1. Find all notes in the deck
        # Use the deck name stored in the anki_client instance
        query = f'"deck:{ANKI_DECK_NAME}"'
        logger.debug(f"Finding notes with query: {query}")
        note_ids = anki_client.find_notes(query)

        if not note_ids:
            logger.info("No notes found in the deck. Backup skipped.")
            # Optionally create an empty CSV with headers
            try:
                with open(CSV_BACKUP_FILE, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
                    writer.writeheader()
                logger.info(f"Created empty backup file with headers: {CSV_BACKUP_FILE}")
            except IOError as e:
                logger.error(f"Failed to write empty backup CSV file: {e}", exc_info=True)
            return

        logger.info(f"Found {len(note_ids)} notes in deck '{ANKI_DECK_NAME}'. Fetching details...")

        # 2. Get info for all notes (consider batching for very large decks)
        notes_info = anki_client.get_notes_info(note_ids)

        rows_to_write = []
        processed_count = 0
        skipped_count = 0

        # 3. Process notes and format for CSV
        for note in notes_info:
            note_id_log = note.get('noteId', 'N/A') # For logging
            try:
                row = {}
                fields = note.get("fields", {})

                # Check if the note uses the expected model (optional but good practice)
                current_model_name = note.get("modelName")
                if current_model_name != ANKI_MODEL_NAME:
                    logger.warning(f"Skipping note ID {note_id_log}: Model mismatch (Expected '{ANKI_MODEL_NAME}', Found '{current_model_name}').")
                    skipped_count += 1
                    continue

                # Map Anki fields to CSV columns using ANKI_FIELD_MAP
                for anki_field, csv_header in ANKI_FIELD_MAP.items():
                    # Check if the field actually exists in the note's data
                    if anki_field in fields:
                        field_data = fields[anki_field]
                        row[csv_header] = field_data.get("value", "") # Get value, default to empty string
                    else:
                        # Field defined in map doesn't exist in this note's model instance
                        logger.warning(f"Field '{anki_field}' not found in note ID {note_id_log} (Model: '{current_model_name}'). Setting empty value in CSV.")
                        row[csv_header] = "" # Assign empty string if field is missing

                # Handle tags - join list into a comma-separated string
                tags = note.get("tags", [])
                row["tags"] = ",".join(tag for tag in tags if tag) # Ensure tags are strings and filter empty ones

                # Basic check: ensure the primary 'word' field is not empty
                word_header = ANKI_FIELD_MAP.get("Word", "word") # Get the CSV header for 'Word'
                if not row.get(word_header):
                     logger.warning(f"Skipping note ID {note_id_log} due to missing or empty primary 'Word' field value.")
                     skipped_count += 1
                     continue

                rows_to_write.append(row)
                processed_count += 1
            except Exception as e:
                logger.error(f"Error processing note ID {note_id_log} for backup: {e}", exc_info=False) # Keep log concise
                skipped_count += 1

        # 4. Write to CSV
        if not rows_to_write:
             logger.warning("No valid notes processed for backup after filtering.")
             # Optionally write just the header if file doesn't exist or is empty
             if not CSV_BACKUP_FILE.exists() or CSV_BACKUP_FILE.stat().st_size == 0:
                 try:
                     with open(CSV_BACKUP_FILE, 'w', newline='', encoding='utf-8') as csvfile:
                         writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
                         writer.writeheader()
                     logger.info(f"Wrote header only to empty backup file: {CSV_BACKUP_FILE}")
                 except IOError as e:
                     logger.error(f"Failed to write header to empty backup CSV file: {e}", exc_info=True)
             return

        logger.info(f"Writing {processed_count} processed notes to CSV...")
        try:
            # Ensure directory exists (should be handled by config.py, but double-check)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(CSV_BACKUP_FILE, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS, extrasaction='ignore') # Ignore extra fields not in headers
                writer.writeheader()
                writer.writerows(rows_to_write)
            logger.info(f"Successfully backed up {processed_count} notes to {CSV_BACKUP_FILE}. Skipped {skipped_count} notes.")
        except IOError as e:
            logger.error(f"Failed to write backup CSV file: {e}", exc_info=True)
        except Exception as e:
             logger.error(f"An unexpected error occurred during CSV writing: {e}", exc_info=True)

    except ConnectionError as e:
        logger.error(f"Anki connection error during backup: {e}. Backup aborted.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during the backup process: {e}", exc_info=True)


# --- Tool Input Model ---
# Define the input structure using Pydantic, FastMCP uses this for validation
class AddWordsInputModel(BaseModel):
    words: List[WordInput] = Field(..., description="Array of words to add (single item for single word)")

# --- Tool Definition ---
# The tool function is now synchronous and takes the Pydantic model directly
# It should return a simple string which FastMCP will wrap appropriately
@mcp.tool(name="add-words-batch")
def add_words_batch(data: AddWordsInputModel) -> str:
    """
    Add words to vocabulary list and create Anki cards (supports both single and batch operations).
    For single word, pass an array with one item. Generates audio using OpenAI TTS.
    Requires Anki to be running with AnkiConnect. Runs synchronously.
    Triggers a full Anki deck backup to CSV after completion.

    IMPORTANT USAGE NOTE FOR CALLER (LLM): Do NOT add any tags to the words unless the end-user explicitly requests specific tags. If the user does not specify tags, the 'tags' field in the input data MUST be omitted or set to null. Do not infer or create tags automatically.
    """
    words_to_process = data.words
    word_count = len(words_to_process)
    is_single_word = word_count == 1
    op_desc = f"word '{words_to_process[0].word}'" if is_single_word else f"{word_count} words"
    logger.info(f"Received request to add {op_desc}")

    results: Dict[str, List[Dict[str, Any]]] = {"success": [], "failed": []}
    processed_count = 0
    any_success = False # Track if at least one word was added successfully

    try:
        # Populate Anki media cache once before starting
        # Consider if this refresh is needed here or just in audio_service
        audio_service._get_anki_media_files(force_refresh=True)

        for word_data in words_to_process:
            processed_count += 1
            logger.info(f"Processing word {processed_count}/{word_count}: '{word_data.word}'")
            try:
                # 1. Validate Input Data
                is_valid, error_msg = validate_word_data(word_data)
                if not is_valid:
                    # Ensure error_msg is a string
                    raise ValueError(str(error_msg) if error_msg else "Invalid word data.")

                # 2. Generate Audio Files (Sequentially)
                audio_results: Dict[str, str] = {}
                try:
                    # Word Audio
                    audio_results["word"] = audio_service.create_audio_file(
                        word_data.word, word_data.word, "word"
                    )
                    # Definition Audio
                    audio_results["definition"] = audio_service.create_audio_file(
                        word_data.definition, word_data.word, "definition"
                    )
                    # Example Audio (if applicable)
                    if word_data.example:
                        audio_results["example"] = audio_service.create_audio_file(
                            word_data.example, word_data.word, "example"
                        )
                except Exception as audio_err:
                     # Log the specific audio error but raise a general failure for the word
                    logger.error(f"Audio generation failed for '{word_data.word}': {audio_err}", exc_info=False)
                    # Re-raise to stop processing this word and record failure
                    raise RuntimeError(f"Audio generation failed.") from audio_err


                # 3. Prepare Anki Fields
                # Ensure all fields expected by your Anki model are present, even if empty
                fields = {
                    "Word": word_data.word,
                    "Definition": word_data.definition,
                    "Example": word_data.example or "",
                    # "Notes": word_data.notes or "", # Include Notes field from input
                    "WordAudio": f"[sound:{audio_results['word']}]" if audio_results.get("word") else "",
                    "DefinitionAudio": f"[sound:{audio_results['definition']}]" if audio_results.get("definition") else "",
                    "ExampleAudio": f"[sound:{audio_results['example']}]" if audio_results.get("example") else "",
                    # Add other fields required by your ANKI_MODEL_NAME here, default to "" if not in input
                    # e.g., "MyOtherField": ""
                }
                logger.debug(f"Prepared fields for Anki note: {fields}")

                # 4. Add Note to Anki (Synchronous)
                note_id = anki_client.add_note(
                    deck_name=ANKI_DECK_NAME,
                    model_name=ANKI_MODEL_NAME,
                    fields=fields,
                    tags=word_data.tags # Pass tags list directly
                )

                # 5. Record Success
                results["success"].append({"word": word_data.word, "note_id": note_id})
                logger.info(f"Successfully added word '{word_data.word}' to Anki (Note ID: {note_id}).")
                any_success = True # Mark that at least one succeeded

            except ValueError as ve: # Catch specific errors like duplicates
                 error_message = str(ve)
                 logger.warning(f"Skipped processing word '{word_data.word}': {error_message}")
                 results["failed"].append({"word": word_data.word, "error": error_message})
            except Exception as e:
                # 6. Record Failure for this specific word
                error_message = str(e)
                logger.error(f"Failed to process word '{word_data.word}': {error_message}", exc_info=False)
                results["failed"].append({"word": word_data.word, "error": error_message})

        # --- Format Response ---
        success_count = len(results["success"])
        failed_count = len(results["failed"])
        response_message = ""

        if is_single_word:
            if success_count == 1:
                response_message = f"✅ Successfully added word: \"{words_to_process[0].word}\""
            else:
                fail_reason = results["failed"][0]['error'] if results["failed"] else "Unknown error"
                response_message = f"❌ Failed to add word \"{words_to_process[0].word}\": {fail_reason}"
        else:
            response_message = f"Batch add complete:\n"
            response_message += f"✅ Successfully added: {success_count} words\n"
            if failed_count > 0:
                response_message += f"❌ Failed: {failed_count} words\n\n"
                response_message += "Failure Details:\n"
                for failure in results["failed"]:
                    response_message += f"- {failure['word']}: {failure['error']}\n"

        logger.info(f"Add operation summary: Success={success_count}, Failed={failed_count}")

        # --- *** TRIGGER BACKUP AFTER PROCESSING *** ---
        # Trigger backup regardless of partial failures to capture the current state.
        logger.info("Attempting post-add Anki deck backup...")
        try:
            backup_anki_deck_to_csv()
            response_message += "\n\n💾 Anki deck backup to CSV completed."
        except Exception as backup_err:
            # Log backup error but don't let it crash the main response
            logger.error(f"An error occurred during the post-add backup: {backup_err}", exc_info=True)
            response_message += "\n\n⚠️ Note: An error occurred during the automatic CSV backup."
        # --- *** END BACKUP TRIGGER *** ---

        return response_message # Return the combined response string

    except ConnectionError as conn_err:
         logger.critical(f"AnkiConnect connection error during batch add: {conn_err}", exc_info=True)
         # Return error string
         return f"Error: Could not connect to Anki. Please ensure Anki is running with AnkiConnect installed and enabled.\nDetails: {conn_err}"
    except Exception as e:
        # Catch-all for unexpected errors during the batch process
        logger.critical(f"Unexpected error during 'add-words-batch' execution: {e}", exc_info=True)
        # Return error string
        return f"An unexpected error occurred while adding words: {e}"

# --- Graceful Shutdown Handling ---
def perform_cleanup():
    logger.info("Performing cleanup before exit...")
    try:
        # Optional: Add backup on exit? Might be slow.
        # logger.info("Performing final backup on exit...")
        # backup_anki_deck_to_csv()
        audio_service.cleanup_unused_audio_files()
    except Exception as e:
        logger.error(f"Error during cleanup on shutdown: {e}", exc_info=True)
    logger.info("Cleanup finished.")

# Register the cleanup function to run on exit
atexit.register(perform_cleanup)

# --- Server Execution ---
if __name__ == "__main__":
    logger.info("Starting Anki MCP server via stdio (Synchronous)...")
    try:
        # Run the server directly (blocking call)
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down.")
        # Cleanup is handled by atexit
        sys.exit(0)
    except Exception as e:
         logger.critical(f"Server failed to run: {e}", exc_info=True)
         sys.exit(1)
    finally:
        # This might be logged before atexit finishes in some scenarios
        logger.info("Server process finishing...")

