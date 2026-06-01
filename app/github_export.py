from __future__ import annotations

import os
import subprocess
from typing import Any


def create_pr_draft(
    *,
    title: str,
    body: str,
    base_branch: str = "main",
) -> dict[str, Any]:
    """Open a pull request when GITHUB_TOKEN and gh CLI are available."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        return {
            "created": False,
            "reason": "Set GITHUB_TOKEN and GITHUB_REPOSITORY to enable PR export",
        }

    env = {**os.environ, "GH_TOKEN": token}
    branch = os.environ.get("REFACTOR_BRANCH", "refactor/agent-suggested")
    cmds = [
        ["git", "checkout", "-b", branch],
        ["git", "add", "-A"],
        ["git", "commit", "-m", title, "--allow-empty"],
        ["git", "push", "-u", "origin", branch],
        [
            "gh",
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--base",
            base_branch,
            "--head",
            branch,
        ],
    ]
    for cmd in cmds[:-1]:
        subprocess.run(cmd, env=env, check=False, capture_output=True)
    proc = subprocess.run(cmds[-1], env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"created": False, "reason": proc.stderr.strip() or proc.stdout.strip()}
    return {"created": True, "url": proc.stdout.strip()}
