import os
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
import logging

# Configure logging (same as before, ensure it doesn't print to stdout)
logger = logging.getLogger("git_diff_mcp")
# Add handlers or configure level as needed, e.g., NullHandler to suppress
logger.addHandler(logging.NullHandler())
# Or configure file logging etc.
# logger.propagate = False # Optional: Prevent propagation if root logger prints

# Initialize FastMCP server
mcp = FastMCP("git_diff_mcp")

# --- Timeout constant ---
GIT_COMMAND_TIMEOUT = 30  # Timeout in seconds for git commands


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


@mcp.tool()
def get_git_commit_diffs(
        commit_ids: Optional[List[str]] = None,
        recent_count: int = 1,
        context_lines: int = 50,
        file_types: Optional[List[str]] = None,
) -> str:
    """
    Retrieves Git commit information and diffs for AI code review.
    (Docstring remains the same - no functional change here)
    ... [rest of the docstring] ...
    """
    # 1. Get Git Repo Path & Validate
    repo_path_str = os.environ.get("GIT_REPO_PATH")
    if not repo_path_str:
        return "Error: GIT_REPO_PATH environment variable not set."

    repo_path = Path(repo_path_str)
    if not repo_path.is_dir():
        return f"Error: GIT_REPO_PATH '{repo_path_str}' is not a valid directory."

    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return f"Error: Directory '{repo_path_str}' does not appear to be a Git repository (.git directory not found)."

    # 2. Determine Target Commit IDs
    target_commit_ids: List[str] = []
    error_messages: List[str] = []

    # Use a consistent way to check for errors from _run_git_command
    def check_command_result(result: subprocess.CompletedProcess, context_msg: str) -> Optional[str]:
        """Checks result and returns error message string if failed, else None."""
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

    if commit_ids:
        # logger.info(f"Fetching specific commit IDs: {commit_ids}")
        target_commit_ids = commit_ids
    else:
        # logger.info(f"Fetching {recent_count} recent commit IDs.")
        if recent_count <= 0:
            return "Error: recent_count must be greater than 0."
        cmd = ["git", "log", f"-n{recent_count}", "--pretty=format:%H", "HEAD"]
        result = _run_git_command(str(repo_path), cmd)

        error = check_command_result(result, "Error fetching recent commit IDs")
        if error:
            error_messages.append(error)
        elif result.stdout:
            target_commit_ids = result.stdout.strip().split("\n")
        else:
            error_messages.append("No recent commits found in the repository (or git log returned empty).")

    if error_messages:
        # Combine and return errors immediately if we couldn't get commit IDs
        return "\n".join(error_messages)

    if not target_commit_ids:
        return "No commits found or specified."

    # logger.info(f"Target commit IDs to process: {target_commit_ids}")

    # 3. Define File Filters
    active_file_types = file_types if file_types else ['.java', '.xml']
    path_filters = [f"*{ft}" for ft in active_file_types]
    # logger.info(f"Using file type filters: {path_filters}")

    # 4. Iterate and Get Diffs for each commit
    markdown_output_parts = []
    markdown_output_parts.append(f"# Git Commit Diff Report")
    markdown_output_parts.append(f"Repository: `{repo_path_str}`")
    markdown_output_parts.append(f"Requested Commits: {' '.join(target_commit_ids)}")
    markdown_output_parts.append(f"Context Lines: {context_lines}")
    markdown_output_parts.append(f"File Types Filtered: `{', '.join(active_file_types)}`")
    markdown_output_parts.append("\n---\n")

    has_content = False
    commit_errors = []  # Collect errors per commit

    for commit_id in target_commit_ids:
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

            result = _run_git_command(str(repo_path), cmd)

            # Check for errors during git show execution
            error = check_command_result(result, f"Processing commit `{commit_id}`")
            if error:
                # Record the error, but continue to next commit
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
                    # Show only commit header part if diff is missing
                    commit_header = diff_content.split('diff --git')[0].strip()
                    if commit_header:  # Display header if it exists
                        markdown_output_parts.append(f"```\n{commit_header}\n```\n")
                    markdown_output_parts.append(
                        f"*(No changes matching file filters `{', '.join(active_file_types)}` found in this commit)*\n")
            else:
                # Successful execution but empty stdout
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


# 5. MCP Runner (for local testing or direct execution)
if __name__ == "__main__":
    # Example usage... (same as before)

    # logger.info("Starting MCP server with stdio transport...")
    mcp.run(transport='stdio')
    # logger.info("MCP server finished.")

