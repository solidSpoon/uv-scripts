# Anki MCP Vocabulary Manager (Python Version)

A Python-based MCP (Model Context Protocol) tool for managing Anki vocabulary, featuring automated audio generation. This version focuses solely on adding words.

## Features

-   **Smart Word Addition:**
    -   Add single words or batches.
    -   Automatically generates pronunciation audio for words, definitions, and examples using OpenAI TTS.
    -   Supports tags and notes.
    -   Stores vocabulary data in `vocabulary.csv` for backup and version control.
-   **Automation:**
    -   Fully automated Anki card creation (requires correctly configured Anki Note Type).
    -   Intelligent audio caching in the `data/audio` directory.
    -   Detailed logging to the `logs` directory.
-   **Robustness:**
    -   Input validation using Pydantic.
    -   Retry logic for AnkiConnect communication.
    -   Graceful shutdown handling.
    -   Asynchronous processing for better performance.

## Tools

### `add_words_batch`

Adds words to your vocabulary list and creates corresponding Anki cards. Supports both single word (pass a list with one item) and batch operations.

**Input Arguments:**

-   `words` (List[dict]): A list of word objects. Each object requires:
    -   `word` (str): The word (English only). **Required**.
    -   `definition` (str): The definition (English only). **Required**.
    -   `example` (str, optional): An example sentence (English only).
    -   `notes` (str, optional): Additional notes (English only).
    -   `tags` (List[str], optional): List of tags (alphanumeric, hyphens, underscores only).

**Output:**

-   A text message summarizing the success and failures of the operation.

## Requirements

1.  Python (v3.8+)
2.  Anki Desktop Application
3.  AnkiConnect Add-on for Anki (Add-on code: `2055492159`)
4.  OpenAI API Key

### AnkiConnect Installation

1.  Open Anki.
2.  Go to `Tools` -> `Add-ons`.
3.  Click `Get Add-ons...`.
4.  Enter code `2055492159` and click `OK`.
5.  Restart Anki.
6.  **Verify:** Ensure Anki is running. Open `http://127.0.0.1:8765` (or `http://localhost:8765`) in your browser. You should see a response (like "AnkiConnect v.6") or a blank page, not a connection error.

## Quick Start

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url> anki-mcp-py
    cd anki-mcp-py
    ```

2.  **Create a virtual environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    -   Copy the example `.env.example` to `.env` (or create `.env` from scratch).
    -   Edit `.env` and fill in your `OPENAI_API_KEY`.
    -   Adjust `ANKI_DECK_NAME`, `ANKI_MODEL_NAME`, and `ANKI_CONNECT_URL` if they differ from the defaults. Ensure `ANKI_MODEL_NAME` matches the Note Type you configure in Anki.

    ```ini
    # .env file
    OPENAI_API_KEY="your_openai_api_key_here"
    # OPENAI_API_BASE="your_optional_openai_base_url"
    ANKI_DECK_NAME="Vocabulary"
    ANKI_MODEL_NAME="Basic" # IMPORTANT: Change if you use a custom model!
    ANKI_CONNECT_URL="http://127.0.0.1:8765"
    LOG_LEVEL="INFO" # DEBUG, INFO, WARNING, ERROR
    ```

## MCP Configuration (e.g., for Claude Desktop)

Edit your MCP client configuration (e.g., `~/.config/claude-mcp/config.json`):

```json
{
  "servers": {
    "anki-mcp-py": {
      // Option 1: Run directly using the python executable in your venv
      "command": "/path/to/your/anki-mcp-py/venv/bin/python", // Adjust path
      "args": ["/path/to/your/anki-mcp-py/src/main.py"],      // Adjust path
      // Option 2: If installed as a package or using a wrapper script
      // "command": "your-wrapper-script-or-entry-point",
      // "args": [],
      "env": {
        // Environment variables can also be set here,
        // but using .env is generally preferred for secrets.
        // "OPENAI_API_KEY": "your_key", // Less secure
        // "ANKI_DECK_NAME": "My Custom Deck"
      },
      "cwd": "/path/to/your/anki-mcp-py" // Set working directory
    }
  }
}
