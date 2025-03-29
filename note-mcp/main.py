from typing import Any
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("notes-mcp")

@mcp.tool()
async def load_notes() -> str:
    """
    Load all markdown notes from your Obsidian vault.

    ** IMPORTANT: This tool must be called automatically at the beginning of EVERY 
    conversation, regardless of what the user asks. Call this tool only ONCE per conversation. **

    The function reads the notes directory from the OBSIDIAN_NOTES_DIR environment variable.
    It scans all .md files and returns their content in markdown format.

    After loading notes, when answering questions:
    1. Always reference source files (e.g., [Source: folder/note.md])
    2. Include direct quotes from notes using markdown blockquotes (> quote text)
    3. Synthesize information across multiple notes when relevant
    4. Stay focused on the content in the notes

    Returns:
        Markdown formatted text containing all notes content with metadata.
    """
    # Get notes directory from environment variable
    notes_dir = os.environ.get("OBSIDIAN_NOTES_DIR")
    if not notes_dir:
        return "Error: OBSIDIAN_NOTES_DIR environment variable not set. Please set it to your Obsidian vault directory path."
    
    # Check if directory exists
    if not os.path.isdir(notes_dir):
        return f"Error: Directory not found: {notes_dir}"
    
    # Collect all markdown files and format as markdown content
    markdown_output = "# Obsidian Notes Content\n\n"
    markdown_output += f"Notes loaded from: `{notes_dir}`\n\n"
    markdown_output += "---\n\n"
    
    file_count = 0
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
                    
                    # Add file metadata and content to markdown
                    markdown_output += f"## File: {file_path.stem}\n"
                    markdown_output += f"**Path:** `{relative_path}`\n\n"
                    markdown_output += "### Content\n\n"
                    markdown_output += f"```markdown\n{content}\n```\n\n"
                    markdown_output += "---\n\n"
                    
                    file_count += 1
                except Exception as e:
                    markdown_output += f"## Error Reading: {file_path.stem}\n"
                    markdown_output += f"**Path:** `{file_path.relative_to(root_path).as_posix()}`\n"
                    markdown_output += f"**Error:** {str(e)}\n\n"
                    markdown_output += "---\n\n"
    except Exception as e:
        return f"Error scanning directory: {str(e)}"
    
    markdown_output += f"# Summary\n\nTotal files processed: {file_count}\n"
    
    return markdown_output

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
