import os
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
import logging

# --- Constants ---
DEFAULT_CONTEXT_LINES = 50
DEFAULT_FILE_TYPES = ['.java', '.xml']  # Fixed file types
GIT_COMMAND_TIMEOUT = 30  # Timeout in seconds for git commands

# Configure logging (same as before, ensure it doesn't print to stdout)
logger = logging.getLogger("git_diff_mcp")
logger.addHandler(logging.NullHandler())  # Suppress logs by default
# logger.propagate = False # Optional: Prevent propagation if root logger prints
# If you need file logging for debugging:
# file_handler = logging.FileHandler("git_diff_mcp.log")
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)
# logger.setLevel(logging.INFO)


# Initialize FastMCP server
mcp = FastMCP("git_diff_mcp")


# --- Helper Functions ---

def _run_git_command(repo_path: str, command: List[str]) -> subprocess.CompletedProcess:
    """
    Helper function to run a git command safely for stdio transport.
    Redirects stdin to DEVNULL and captures output. Includes timeout.
    """
    try:
        # logger.info(f"Running command: {' '.join(command)} in {repo_path}")
        result = subprocess.run(
            command,
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            stdin=subprocess.DEVNULL,  # *** CRUCIAL: Prevent git from reading stdin ***
            timeout=GIT_COMMAND_TIMEOUT  # *** ADDED: Prevent indefinite hangs ***
        )
        # logger.info(f"Command finished with code: {result.returncode}")
        return result
    except FileNotFoundError:
        # logger.error("Git command not found.")
        return subprocess.CompletedProcess(
            args=command,
            returncode=-1,
            stdout="",
            stderr="Git command not found. Make sure Git is installed and in the system's PATH."
        )
    except subprocess.TimeoutExpired:
        # logger.error(f"Git command timed out after {GIT_COMMAND_TIMEOUT} seconds: {' '.join(command)}")
        return subprocess.CompletedProcess(
            args=command,
            returncode=-3,  # Use a distinct code for timeout
            stdout="",
            stderr=f"Git command timed out after {GIT_COMMAND_TIMEOUT} seconds. The repository might be very large, the command stuck, or requires interaction."
        )
    except Exception as e:
        # logger.error(f"Exception running git command: {e}", exc_info=True)
        return subprocess.CompletedProcess(
            args=command,
            returncode=-2,
            stdout="",
            stderr=f"An unexpected error occurred while running git: {str(e)}"
        )


def _check_command_result(result: subprocess.CompletedProcess, context_msg: str) -> Optional[str]:
    """Checks subprocess result and returns formatted error message string if failed, else None."""
    if result.returncode != 0:
        err_msg = f"{context_msg}: Git command failed (code {result.returncode})."
        # Include stderr if it provides useful info
        if result.stderr:
            # Limit stderr length to avoid overly long messages
            stderr_snippet = result.stderr.strip()[:500]
            err_msg += f"\nDetails: {stderr_snippet}"
            if len(result.stderr.strip()) > 500:
                err_msg += "..."
        # Special handling for our custom error codes
        elif result.returncode == -1:  # FileNotFoundError
            err_msg = f"{context_msg}: {result.stderr}"  # Already formatted message
        elif result.returncode == -3:  # TimeoutExpired
            err_msg = f"{context_msg}: {result.stderr}"  # Already formatted message
        return err_msg
    return None


def _get_repo_path() -> Optional[Path]:
    """Gets and validates the GIT_REPO_PATH environment variable."""
    repo_path_str = os.environ.get("GIT_REPO_PATH")
    if not repo_path_str:
        # logger.error("GIT_REPO_PATH environment variable not set.")
        return None  # Signal error upstream

    repo_path = Path(repo_path_str)
    if not repo_path.is_dir():
        # logger.error(f"GIT_REPO_PATH '{repo_path_str}' is not a valid directory.")
        return None  # Signal error upstream

    git_dir = repo_path / ".git"
    if not git_dir.exists():
        # logger.error(f"Directory '{repo_path_str}' does not appear to be a Git repository.")
        return None  # Signal error upstream

    return repo_path


def _generate_diff_markdown(
        commit_ids: List[str],
        repo_path: Path,
        context_lines: int,
        file_types: List[str]
) -> str:
    """
    Core logic to fetch diffs for given commit IDs and format as Markdown.
    """
    path_filters = [f"*{ft}" for ft in file_types]
    repo_path_str = str(repo_path)  # For display

    markdown_output_parts = []
    markdown_output_parts.append(f"# Git Commit Diff Report")
    markdown_output_parts.append(f"Repository: `{repo_path_str}`")
    # Be careful listing too many commit IDs here if the list is huge
    commits_display = ' '.join(commit_ids[:5]) + ('...' if len(commit_ids) > 5 else '')
    markdown_output_parts.append(f"Processing Commits: `{commits_display}` ({len(commit_ids)} total)")
    markdown_output_parts.append(f"Context Lines: `{context_lines}` (Fixed)")
    markdown_output_parts.append(f"File Types Filtered: `{', '.join(file_types)}` (Fixed)")
    markdown_output_parts.append("\n---\n")

    has_content = False
    commit_errors = []  # Collect errors per commit

    for commit_id in commit_ids:
        commit_id = commit_id.strip()
        if not commit_id:
            continue

        # logger.info(f"Processing commit: {commit_id}")
        markdown_output_parts.append(f"## Commit: `{commit_id}`\n")

        try:
            cmd = [
                "git",
                "show",
                "--no-color",
                f"--unified={context_lines}",
                commit_id,
                "--",
            ]
            cmd.extend(path_filters)

            result = _run_git_command(repo_path_str, cmd)

            # Check for errors during git show execution
            error = _check_command_result(result, f"Processing commit `{commit_id}`")
            if error:
                commit_errors.append(error)
                markdown_output_parts.append(f"**Error:**\n```\n{error}\n```\n")

            # Process successful or partially successful execution
            elif result.stdout:
                diff_content = result.stdout.strip()
                if "diff --git" in diff_content:
                    markdown_output_parts.append(f"```diff\n{diff_content}\n```\n")
                    has_content = True
                else:
                    # Git show succeeded but no files matched the filters
                    commit_header = diff_content.split('diff --git')[0].strip()
                    if commit_header:
                        markdown_output_parts.append(f"```\n{commit_header}\n```\n")
                    markdown_output_parts.append(
                        f"*(No changes matching file filters `{', '.join(file_types)}` found in this commit)*\n")
            else:
                markdown_output_parts.append(
                    f"*(No output returned for commit `{commit_id}`. This might indicate an empty commit or issue with filters.)*\n")

        except Exception as e:
            # logger.error(f"Unexpected Python error processing commit {commit_id}: {e}", exc_info=True)
            error_msg = f"Internal Python Error processing commit `{commit_id}`: {str(e)}"
            commit_errors.append(error_msg)
            markdown_output_parts.append(f"**Error:**\n```\n{error_msg}\n```\n")

        markdown_output_parts.append("---\n")  # Separator between commits

    # Add a summary section for errors encountered
    if commit_errors:
        markdown_output_parts.append("## Processing Errors Summary\n")
        for i, err in enumerate(commit_errors):
            markdown_output_parts.append(f"{i + 1}. {err}\n")
        markdown_output_parts.append("---\n")

    if not has_content and not commit_errors:
        markdown_output_parts.append(
            "\n*Summary: No code changes matching the specified filters were found in the requested commits.*")
    elif not has_content and commit_errors:
        markdown_output_parts.append(
            "\n*Summary: No matching code changes were found, and some errors occurred during processing.*")

    return "\n".join(markdown_output_parts)


# --- MCP Tools ---

@mcp.tool()
def get_recent_commits_diff(recent_count: int = 1) -> str:
    """
    Retrieves diffs for the N most recent commits on the current branch.

    Fetches details for the specified number of recent commits.
    Includes commit metadata (author, date, message) and code diffs.
    Context lines are fixed at 50.
    File types are fixed to '.java' and '.xml'.
    Output is formatted in Markdown for AI review.

    Args:
        recent_count (int): The number of most recent commits to fetch.
                            Must be > 0. Defaults to 1.

    Returns:
        str: A Markdown formatted string containing commit details and diffs,
             or an error message.
    """
    # logger.info(f"Tool 'get_recent_commits_diff' called with recent_count={recent_count}")
    repo_path = _get_repo_path()
    if repo_path is None:
        return "Error: GIT_REPO_PATH environment variable not set, invalid, or not a Git repository."

    if not isinstance(recent_count, int) or recent_count <= 0:
        return "Error: recent_count must be a positive integer."

    # Get the hashes of the most recent N commits
    cmd_log = ["git", "log", f"-n{recent_count}", "--pretty=format:%H", "HEAD"]
    result_log = _run_git_command(str(repo_path), cmd_log)

    error_log = _check_command_result(result_log, "Error fetching recent commit IDs")
    if error_log:
        return f"# Git Commit Diff Report\nError:\n```\n{error_log}\n```"  # Return formatted error

    commit_ids = []
    if result_log.stdout:
        commit_ids = result_log.stdout.strip().split("\n")

    if not commit_ids:
        return "# Git Commit Diff Report\n*No recent commits found in the repository.*\n"

    # Call the core markdown generation function
    return _generate_diff_markdown(
        commit_ids=commit_ids,
        repo_path=repo_path,
        context_lines=DEFAULT_CONTEXT_LINES,
        file_types=DEFAULT_FILE_TYPES
    )


@mcp.tool()
def get_specific_commits_diff(commit_ids: List[str]) -> str:
    """
    Retrieves diffs for a specific list of commit IDs.

    Fetches details for each commit ID provided in the list.
    Includes commit metadata (author, date, message) and code diffs.
    Context lines are fixed at 50.
    File types are fixed to '.java' and '.xml'.
    Output is formatted in Markdown for AI review.

    Args:
        commit_ids (List[str]): A list of specific commit IDs (hashes)
            to fetch diffs for. Must not be empty.

    Returns:
        str: A Markdown formatted string containing commit details and diffs,
             or an error message.
    """
    # logger.info(f"Tool 'get_specific_commits_diff' called with {len(commit_ids)} commit IDs.")
    repo_path = _get_repo_path()
    if repo_path is None:
        return "Error: GIT_REPO_PATH environment variable not set, invalid, or not a Git repository."

    if not isinstance(commit_ids, list) or not commit_ids:
        return "Error: commit_ids must be a non-empty list of strings."

    # Basic validation for commit hash format (optional but good)
    valid_ids = []
    invalid_entries = []
    for cid in commit_ids:
        if isinstance(cid, str) and cid.strip():  # Basic check: is string and not empty
            # A more thorough check could use regex for hex characters, but git handles bad IDs
            valid_ids.append(cid.strip())
        else:
            invalid_entries.append(str(cid))  # Keep track of invalid entries

    if not valid_ids:
        return f"Error: No valid commit IDs provided in the list. Invalid entries found: {', '.join(invalid_entries)}"

    if invalid_entries:
        # logger.warning(f"Invalid entries found in commit_ids list and were ignored: {invalid_entries}")
        pass  # Decide if you want to notify about ignored invalid entries in the final output or just log it.
        # For now, we just proceed with the valid ones.

    # Call the core markdown generation function
    return _generate_diff_markdown(
        commit_ids=valid_ids,  # Use only the valid IDs
        repo_path=repo_path,
        context_lines=DEFAULT_CONTEXT_LINES,
        file_types=DEFAULT_FILE_TYPES
    )


# --- MCP Runner ---
if __name__ == "__main__":
    # Example usage check (won't run unless GIT_REPO_PATH is set):
    # if "GIT_REPO_PATH" in os.environ:
    #     print("--- Testing Recent Commits (Manual) ---")
    #     output_recent = get_recent_commits_diff(recent_count=2)
    #     print(output_recent)

    #     print("\n--- Testing Specific Commits (Manual - replace with real IDs) ---")
    #     # Find commit IDs in your test repo first, e.g., using git log
    #     test_commit_ids = ["<your_commit_id_1>", "<your_commit_id_2>"] # Replace placeholders
    #     if "<your_commit_id_1>" not in test_commit_ids: # Simple check if placeholder was replaced
    #         output_specific = get_specific_commits_diff(commit_ids=test_commit_ids)
    #         print(output_specific)
    #     else:
    #         print("Skipping specific commit test, please provide real commit IDs.")
    # else:
    #     print("Set the GIT_REPO_PATH environment variable to run manual tests.")

    # Initialize and run the server using stdio transport
    # logger.info("Starting MCP server with stdio transport...")
    mcp.run(transport='stdio')
    # logger.info("MCP server finished.")

