# Workspace Rules - Versioning & Release Workflow

When making any code changes or adding features to this repository, the agent must adhere to the following workflow:

## 1. Version Incrementing

- Increment the application version string `VERSION` in `backend/config.py` by `0.01` (patch level increment, e.g. `1.0.1` -> `1.0.2`).
- **CRITICAL — Always sync `FRONTEND_VERSION`**: The constant `FRONTEND_VERSION` in `static/index.html` (Alpine.js data block) **must always be updated to match `config.py`**. Failure to do this causes the post-update cache-bust logic in `checkForUpdates()` to detect a mismatch, triggering a reload loop where users continue to see the old version number after updating. Search for `FRONTEND_VERSION:` in `static/index.html` and update it to the new version string every time.

## 2. Changelog Documentation

- Add a detailed entry to `CHANGELOG.md` in the root directory under a section with the new version and current date, detailing all additions, changes, or deprecations.

## 3. Dashboard Compatibility

- Ensure the dashboard `checkForUpdates()` method and the software update card in `static/index.html` remain fully compatible, as they display this version and release changelog.

## 4. Git Commits & GitHub Release — Exact Working Commands

Do this yourself directly using `run_command`. Do NOT delegate to a subagent for this — it is slow. Use these exact commands sequentially:

### Stage and commit:
```powershell
git -C "x:\Antigravity Dev Work\ZeroSink" add -A
git -C "x:\Antigravity Dev Work\ZeroSink" commit -m "your commit message here"
git -C "x:\Antigravity Dev Work\ZeroSink" push origin main
```

### CRITICAL — Create and push the git tag:
The in-app updater downloads: `https://github.com/devslice/zerosink/archive/refs/tags/v{VERSION}.tar.gz`
**If no matching tag exists, this URL returns 404 and the update silently fails.**
Always create and push the tag AFTER the commit is pushed:
```powershell
git -C "x:\Antigravity Dev Work\ZeroSink" tag v{VERSION}
git -C "x:\Antigravity Dev Work\ZeroSink" push origin v{VERSION}
```
If the tag already exists remotely and needs to be updated:
```powershell
git -C "x:\Antigravity Dev Work\ZeroSink" tag -f v{VERSION}
git -C "x:\Antigravity Dev Work\ZeroSink" push origin v{VERSION} --force
```

### Create a GitHub Release via MCP (github-mcp-server):
Use the `create_or_update_file` or the appropriate release tool from `github-mcp-server`. The release tool is lazily loaded — call it via `call_mcp_tool`:
- **Server**: `github-mcp-server`
- **Tool**: Look up the correct tool from the schema. For creating releases, the tool is likely something like `create_release` — check `C:\Users\Ant\.gemini\antigravity\mcp\github-mcp-server\` for available tool schemas.
- **Repo**: `devslice/zerosink`
- **Tag**: `v{VERSION}` (e.g. `v1.0.9`)
- **Release notes**: Must match the CHANGELOG entry exactly, as the dashboard update engine reads `body` from the GitHub Releases API to display update details.

### CRITICAL Release Notes Rule:
Always supply the full changelog entry as the release `body`. The dashboard fetches `https://api.github.com/repos/devslice/zerosink/releases/latest` and displays `data.body` directly to users in the update card.
