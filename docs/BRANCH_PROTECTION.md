# Branch protection

Recommended GitHub settings for `main`:

1. Require a pull request before merging (at least one approval for team repos).
2. Require required status checks to pass:
   - `Lint & format`
   - `Type check`
   - `Unit tests`
   - `Validate PR draft payload` (workflow `PR export checks`)
3. Require branches to be up to date before merging.
4. Block force pushes and deletion of `main`.

Set repository secrets when enabling automated PR export:

- `GITHUB_TOKEN` — workflow token or PAT with `contents` and `pull_requests` scope
- `GITHUB_REPOSITORY` — `owner/repo`
- Optional `REFACTOR_BRANCH` — branch name for agent commits (default `refactor/agent-suggested`)
