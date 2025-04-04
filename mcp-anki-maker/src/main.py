import atexit
import sys
from typing import List, Dict, Any
import logging

# Use Pydantic directly for input model definition
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from openai import OpenAI # Use synchronous client

from .config import (
    OPENAI_API_KEY, OPENAI_API_BASE, ANKI_DECK_NAME, ANKI_MODEL_NAME, logger
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
    description="Synchronous Python version of Anki MCP for adding vocabulary with audio.",
    logger=logger
)

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
    """
    words_to_process = data.words
    word_count = len(words_to_process)
    is_single_word = word_count == 1
    op_desc = f"word '{words_to_process[0].word}'" if is_single_word else f"{word_count} words"
    logger.info(f"Received request to add {op_desc}")

    results: Dict[str, List[Dict[str, Any]]] = {"success": [], "failed": []}
    processed_count = 0

    try:
        # Populate Anki media cache once before starting
        audio_service._get_anki_media_files(force_refresh=True)

        for word_data in words_to_process:
            processed_count += 1
            logger.info(f"Processing word {processed_count}/{word_count}: '{word_data.word}'")
            try:
                # 1. Validate Input Data
                is_valid, error_msg = validate_word_data(word_data)
                if not is_valid:
                    raise ValueError(error_msg or "Invalid word data.")

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
                fields = {
                    "Word": word_data.word,
                    "Definition": word_data.definition,
                    "Example": word_data.example or "",
                    "WordAudio": f"[sound:{audio_results['word']}]" if audio_results.get("word") else "",
                    "DefinitionAudio": f"[sound:{audio_results['definition']}]" if audio_results.get("definition") else "",
                    "ExampleAudio": f"[sound:{audio_results['example']}]" if audio_results.get("example") else "",
                    # Add other fields from your model if necessary, ensuring they exist even if empty
                }
                logger.debug(f"Prepared fields for Anki note: {fields}")

                # 4. Add Note to Anki (Synchronous)
                note_id = anki_client.add_note(
                    deck_name=ANKI_DECK_NAME,
                    model_name=ANKI_MODEL_NAME,
                    fields=fields,
                    tags=word_data.tags
                )

                # 5. Record Success
                results["success"].append({"word": word_data.word, "note_id": note_id})
                logger.info(f"Successfully added word '{word_data.word}' to Anki (Note ID: {note_id}).")

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
        return response_message # Return simple string

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
        audio_service.cleanup_unused_audio_files()
    except Exception as e:
        logger.error(f"Error during audio cleanup on shutdown: {e}", exc_info=True)
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
        logger.info("Server process finished.") # Will be logged after cleanup

