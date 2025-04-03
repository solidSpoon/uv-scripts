import os
import subprocess
from pathlib import Path
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

# 初始化 FastMCP 服务
mcp = FastMCP("git-review-mcp")


# --- 辅助函数 ---

def _run_git_command(repo_path: str, command: List[str]) -> subprocess.CompletedProcess:
    """执行 git 命令并捕获输出，处理基本错误"""
    try:
        result = subprocess.run(
            ['git'] + command,
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False  # 我们将手动检查返回码
        )
        return result
    except FileNotFoundError:
        # Git 未安装或不在 PATH 中
        raise RuntimeError("Error: 'git' command not found. Please ensure Git is installed and in your PATH.")
    except Exception as e:
        # 其他潜在错误 (例如权限问题)
        raise RuntimeError(f"An unexpected error occurred while running git: {e}")


def _format_commit_diff_md(commit_hash: str, git_show_output: str, error_msg: Optional[str] = None) -> str:
    """将 'git show' 的输出格式化为 Markdown"""
    md_output = f"## Commit: `{commit_hash}`\n\n"

    if error_msg:
        md_output += f"**Error processing commit:**\n```\n{error_msg}\n```\n"
        md_output += "---\n\n"
        return md_output

    if not git_show_output:
        md_output += "**Warning:** No output received from `git show`. This might mean the commit is invalid, empty, or an issue occurred.\n"
        md_output += "---\n\n"
        return md_output

    # 分离提交信息和 diff 内容
    # 'git show --pretty=...' 的输出通常包含 Commit 信息，然后是 diff
    # diff 内容通常以 "diff --git" 开头
    try:
        diff_start_index = git_show_output.index("diff --git")
        commit_info = git_show_output[:diff_start_index].strip()
        diff_content = git_show_output[diff_start_index:]
    except ValueError:
        # 没有找到 "diff --git"，可能此提交没有代码更改（或者只更改了我们过滤掉的文件）
        commit_info = git_show_output.strip()
        diff_content = "*No relevant code changes (.java or .xml) found in this commit.*"

    md_output += "### Commit Details\n"
    md_output += f"```\n{commit_info}\n```\n\n"  # 使用普通代码块显示提交信息

    md_output += "### Code Changes (.java, .xml)\n"
    if diff_content.startswith("diff --git"):
        md_output += f"```diff\n{diff_content}\n```\n"  # 使用 diff 代码块显示差异
    else:
        md_output += f"{diff_content}\n"  # 显示提示信息

    md_output += "---\n\n"  # 分隔符
    return md_output


def _get_single_commit_info(repo_path: str, commit_id: str, context_lines: int) -> str:
    """获取单个提交的信息并格式化"""
    git_command = [
        'show',
        f'-U{context_lines}',
        '--pretty=fuller',  # 显示更完整的作者/提交者信息和日期
        # '--word-diff=color', # 更清晰地显示单词级别的差异（可选，但对审查有帮助）
        # '--color=always', # 强制颜色输出，diff块会更好看（虽然md可能不渲染）
        commit_id,
        '--',  # 分隔符，后面是路径过滤器
        '*.java',
        '*.xml'
    ]

    result = _run_git_command(repo_path, git_command)

    if result.returncode != 0:
        error_message = f"Git command failed with exit code {result.returncode}.\nStderr:\n{result.stderr}"
        # 即使出错，也尝试格式化，包含错误信息
        return _format_commit_diff_md(commit_id, result.stdout, error_message)
    elif not result.stdout.strip() and not "diff --git" in result.stdout:
        # 命令成功，但没有输出 stdout，可能是因为没有匹配的文件更改
        # 尝试获取基础提交信息，但不包括 diff
        info_command = ['show', '--pretty=fuller', '--no-patch', commit_id]
        info_result = _run_git_command(repo_path, info_command)
        if info_result.returncode == 0:
            return _format_commit_diff_md(commit_id, info_result.stdout)
        else:
            # 如果连获取基本信息都失败，报告原始错误
            error_message = f"Git command failed to get base info. Stderr:\n{info_result.stderr}"
            return _format_commit_diff_md(commit_id, "", error_message)

    return _format_commit_diff_md(commit_id, result.stdout)


# --- MCP 工具 ---

@mcp.tool()
def get_recent_commits_diff(n: int = 1, context_lines: int = 50) -> str:
    """
    获取当前分支最近 N 次提交中 .java 和 .xml 文件的变更。

    从 GIT_REPO_PATH 环境变量指定的 Git 仓库获取信息。
    返回 Markdown 格式的字符串，包含提交详情和带指定上下文行数的代码差异。

    Args:
        n (int): 要获取的最近提交数量 (默认为 1)。
        context_lines (int): 代码差异显示的上下文行数 (默认为 50)。

    Returns:
        str: Markdown 格式的提交信息和代码差异，或错误信息。
    """
    repo_path = os.environ.get("GIT_REPO_PATH")
    if not repo_path:
        return "Error: GIT_REPO_PATH environment variable not set."
    if not Path(repo_path).is_dir():
        return f"Error: GIT_REPO_PATH '{repo_path}' is not a valid directory."
    if not Path(repo_path, '.git').exists():
        return f"Error: Directory '{repo_path}' does not appear to be a Git repository."

    if n <= 0:
        return "Error: Number of commits 'n' must be greater than 0."

    # 1. 获取最近 n 次提交的 ID
    log_command = ['log', f'-n{n}', '--pretty=format:%H']  # %H 获取完整的 commit hash
    log_result = _run_git_command(repo_path, log_command)

    if log_result.returncode != 0:
        return f"Error getting commit logs:\n```\n{log_result.stderr}\n```"

    commit_ids = log_result.stdout.strip().split('\n')
    if not commit_ids or not commit_ids[0]:
        return f"No commits found in repository '{repo_path}' or an error occurred."

    # 2. 逐个获取并格式化每个提交的 diff
    all_diffs_md = f"# Reviewing Last {len(commit_ids)} Commit(s) in '{repo_path}'\n\n"
    all_diffs_md += f"Showing changes for `.java` and `.xml` files with `{context_lines}` lines of context.\n\n"
    all_diffs_md += "---\n\n"

    try:
        for commit_id in commit_ids:
            all_diffs_md += _get_single_commit_info(repo_path, commit_id, context_lines)
    except Exception as e:
        all_diffs_md += f"\n\n**An unexpected error occurred during processing:**\n```\n{str(e)}\n```"

    return all_diffs_md


@mcp.tool()
def get_specific_commits_diff(commit_ids: List[str], context_lines: int = 50) -> str:
    """
    获取指定提交 ID 列表中 .java 和 .xml 文件的变更。

    从 GIT_REPO_PATH 环境变量指定的 Git 仓库获取信息。
    返回 Markdown 格式的字符串，包含提交详情和带指定上下文行数的代码差异。

    Args:
        commit_ids (List[str]): 要获取信息的提交 ID 列表。
        context_lines (int): 代码差异显示的上下文行数 (默认为 50)。

    Returns:
        str: Markdown 格式的提交信息和代码差异，或错误信息。
    """
    repo_path = os.environ.get("GIT_REPO_PATH")
    if not repo_path:
        return "Error: GIT_REPO_PATH environment variable not set."
    if not Path(repo_path).is_dir():
        return f"Error: GIT_REPO_PATH '{repo_path}' is not a valid directory."
    if not Path(repo_path, '.git').exists():
        return f"Error: Directory '{repo_path}' does not appear to be a Git repository."

    if not commit_ids:
        return "Error: No commit IDs provided."

    all_diffs_md = f"# Reviewing {len(commit_ids)} Specific Commit(s) in '{repo_path}'\n\n"
    all_diffs_md += f"Showing changes for `.java` and `.xml` files with `{context_lines}` lines of context.\n\n"
    all_diffs_md += "---\n\n"

    try:
        for commit_id in commit_ids:
            # 基本的 ID 格式检查 (可以更严格)
            if not commit_id or len(commit_id) < 6:  # Git 短 hash 通常至少 6-7 位
                all_diffs_md += f"## Commit: `{commit_id}`\n\n**Error:** Invalid or too short commit ID provided.\n\n---\n\n"
                continue
            all_diffs_md += _get_single_commit_info(repo_path, commit_id, context_lines)
    except Exception as e:
        all_diffs_md += f"\n\n**An unexpected error occurred during processing:**\n```\n{str(e)}\n```"

    return all_diffs_md


def test_git_review_mcp():
    """测试 Git Review MCP 功能"""
    # 确保设置了环境变量
    repo_path = os.environ.get("GIT_REPO_PATH")
    if not repo_path:
        print("请先设置 GIT_REPO_PATH 环境变量，指向一个 Git 仓库")
        return
    print(f"使用仓库: {repo_path}")

    # 测试最近提交
    print("\n=== 测试获取最近 1 次提交 ===")
    result = get_recent_commits_diff(n=1, context_lines=20)
    print(result)

    # 测试最近多次提交
    print("\n=== 测试获取最近 2 次提交 ===")
    result = get_recent_commits_diff(n=2, context_lines=10)
    print(result)

    # 获取最近的 commit ID 用于测试特定提交
    try:
        recent_commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True
        ).stdout.strip()

        print(f"\n=== 测试获取特定提交 {recent_commit[:8]} ===")
        result = get_specific_commits_diff(commit_ids=[recent_commit], context_lines=15)
        print(result)
    except Exception as e:
        print(f"获取当前提交失败: {e}")

    print("\n测试完成!")


# 当直接运行此脚本时执行测试
if __name__ == "__main__":
    # test_git_review_mcp()
    mcp.run(transport='stdio')
