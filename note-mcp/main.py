from typing import Any
import os
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("obsidian_notes_assistant")

@mcp.tool()
async def load_notes() -> str:
    """
    Load all markdown notes from your Obsidian vault.
    
    This function should be called once at the beginning of the conversation.
    After loading the notes, I'll be able to answer questions based on their content.
    
    The function reads the notes directory from the OBSIDIAN_NOTES_DIR environment variable.
    It scans all .md files and returns their content.
    
    When answering questions, I'll:
    1. Reference the source file (e.g., [Source: folder/note.md])
    2. Include relevant quotes from your notes
    3. Synthesize information from multiple notes when appropriate
    
    Returns:
        JSON containing all notes content and metadata.
    """
    # Get notes directory from environment variable
    notes_dir = os.environ.get("OBSIDIAN_NOTES_DIR")
    if not notes_dir:
        return "Error: OBSIDIAN_NOTES_DIR environment variable not set. Please set it to your Obsidian vault directory path."
    
    # Check if directory exists
    if not os.path.isdir(notes_dir):
        return f"Error: Directory not found: {notes_dir}"
    
    # Collect all markdown files
    notes = []
    root_path = Path(notes_dir)
    
    try:
        for file_path in root_path.glob("**/*.md"):
            if file_path.is_file():
                try:
                    # Read file content
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    # Get relative path from the notes directory
                    relative_path = file_path.relative_to(root_path).as_posix()
                    
                    notes.append({
                        "path": relative_path,
                        "title": file_path.stem,  # Use filename without extension as title
                        "content": content
                    })
                except Exception as e:
                    notes.append({
                        "path": file_path.relative_to(root_path).as_posix(),
                        "error": f"Failed to read file: {str(e)}"
                    })
    except Exception as e:
        return f"Error scanning directory: {str(e)}"
    
    result = {
        "notes": notes,
        "total_files": len(notes)
    }
    
    return json.dumps(result, ensure_ascii=False)

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
