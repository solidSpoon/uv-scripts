import base64
import logging
from pathlib import Path
from typing import Optional, Set # Corrected import
from openai import OpenAI, APIError, RateLimitError

from .config import AUDIO_DIR, logger
from .utils import format_word_for_filename, get_stable_hash
from .anki_connect import AnkiConnectClient

class AudioService:
    """Handles TTS generation and caching (Synchronous)."""

    def __init__(self, openai_client: OpenAI, anki_client: AnkiConnectClient):
        self.openai = openai_client
        self.anki = anki_client
        self.audio_dir = AUDIO_DIR
        self.logger = logger
        self._anki_media_cache: Optional[Set[str]] = None # Cache Anki media files

    def _get_anki_media_files(self, force_refresh: bool = False) -> Set[str]:
        """Gets and caches the list of media files from Anki (Synchronous)."""
        if self._anki_media_cache is None or force_refresh:
            try:
                self.logger.debug("Fetching media file list from Anki...")
                filenames = self.anki.get_media_files_names() # Direct sync call
                self._anki_media_cache = set(filenames)
                self.logger.debug(f"Cached {len(self._anki_media_cache)} Anki media filenames.")
            except Exception as e:
                self.logger.error(f"Failed to get Anki media files: {e}. Audio caching might be incomplete.", exc_info=True)
                return set() # Return empty set on error
        # Ensure cache is not None before returning
        return self._anki_media_cache if self._anki_media_cache is not None else set()


    def create_audio_file(self, text: str, word: str, audio_type: str) -> str:
        """
        Creates an MP3 audio file for the given text using OpenAI TTS (Synchronous).
        Caches locally and uploads to Anki if needed.
        Returns the filename (e.g., 'word-type-hash.mp3').
        """
        if not text:
            self.logger.warning(f"Attempted to create audio for empty text (word: {word}, type: {audio_type}). Skipping.")
            return ""

        formatted_word = format_word_for_filename(word)
        stable_hash = get_stable_hash(text)
        audio_filename = f"{formatted_word}-{audio_type}-{stable_hash}.mp3"
        audio_path = self.audio_dir / audio_filename

        try:
            # 1. Check local cache
            if audio_path.exists():
                self.logger.debug(f"Audio file found locally: {audio_filename}")
                # 2. Check if it's in Anki (force refresh might be too slow here, use cache)
                anki_files = self._get_anki_media_files() # Use cached version for speed
                if audio_filename not in anki_files:
                    self.logger.info(f"File '{audio_filename}' exists locally but not in Anki. Uploading...")
                    try:
                        with open(audio_path, "rb") as f:
                            audio_data = f.read()
                        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                        # Upload synchronously
                        self.anki.store_media_file(audio_filename, audio_base64)
                        # Refresh cache after successful upload
                        self._get_anki_media_files(force_refresh=True)
                    except Exception as e:
                        self.logger.error(f"Failed to upload existing local file '{audio_filename}' to Anki: {e}", exc_info=True)
                        # Proceed, returning filename as local file exists
                return audio_filename

            # 3. File doesn't exist locally, generate TTS
            self.logger.info(f"Generating TTS audio for '{audio_filename}'...")
            try:
                # Synchronous API call
                response = self.openai.audio.speech.create(
                    model="tts-1",
                    voice="alloy",
                    input=text,
                    response_format="mp3"
                )
                # Get binary content directly
                audio_data = response.content

            except RateLimitError as e:
                 self.logger.error(f"OpenAI TTS rate limit hit for '{audio_filename}': {e}", exc_info=True)
                 raise RuntimeError(f"OpenAI API rate limit exceeded.") from e
            except APIError as e:
                self.logger.error(f"OpenAI TTS API error for '{audio_filename}': {e}", exc_info=True)
                raise RuntimeError(f"OpenAI API error: {e.status_code} - {e.message}") from e
            except Exception as e:
                self.logger.error(f"Unexpected error during TTS generation for '{audio_filename}': {e}", exc_info=True)
                raise RuntimeError(f"Failed to generate TTS audio.") from e

            # 4. Save locally
            try:
                with open(audio_path, "wb") as f:
                    f.write(audio_data)
                self.logger.debug(f"Saved TTS audio locally: {audio_path}")
            except IOError as e:
                 self.logger.error(f"Failed to save audio file locally '{audio_path}': {e}", exc_info=True)
                 # Continue to upload to Anki if possible

            # 5. Upload to Anki
            try:
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                # Synchronous upload
                self.anki.store_media_file(audio_filename, audio_base64)
                 # Refresh cache after successful upload
                self._get_anki_media_files(force_refresh=True)
            except Exception as e:
                 # Error already logged in anki_connect.py
                 raise RuntimeError(f"Failed to upload generated audio '{audio_filename}' to Anki.") from e

            return audio_filename

        except Exception as e:
            # Log error specific to this audio file creation attempt
            self.logger.error(f"Error processing audio for word '{word}', type '{audio_type}': {e}", exc_info=True)
            # Re-raise to signal failure for the word processing
            raise RuntimeError(f"Failed to create/retrieve audio for '{word}' ({audio_type}).") from e

    def cleanup_unused_audio_files(self):
        """Deletes local audio files not in Anki's media collection (Synchronous)."""
        self.logger.info("Starting cleanup of unused local audio files...")
        try:
            local_files = {f.name for f in self.audio_dir.glob("*.mp3") if f.is_file()}
            # Force refresh on cleanup
            anki_files = self._get_anki_media_files(force_refresh=True)

            unused_files = local_files - anki_files
            deleted_count = 0
            for filename in unused_files:
                file_path = self.audio_dir / filename
                try:
                    file_path.unlink()
                    self.logger.debug(f"Deleted unused local audio file: {filename}")
                    deleted_count += 1
                except OSError as e:
                    self.logger.error(f"Failed to delete unused file '{filename}': {e}", exc_info=True)

            self.logger.info(f"Audio cleanup finished. Deleted {deleted_count} unused files.")

        except Exception as e:
            self.logger.error(f"Error during audio cleanup: {e}", exc_info=True)

