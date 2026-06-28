# Workspace Rules - Versioning & Release Workflow

When making any code changes or adding features to this repository, the agent must adhere to the following workflow:

1. **Version Incrementing**:
   - Increment the application version string `VERSION` in `backend/config.py` by `0.01` (patch level increment, e.g. `1.0.1` -> `1.0.2`).
   
2. **Changelog Documentation**:
   - Add a detailed entry to `CHANGELOG.md` in the root directory under a section with the new version and current date, detailing all additions, changes, or deprecations.

3. **Dashboard Compatibility**:
   - Ensure the dashboard `checkForUpdates()` method and the software update card in `static/index.html` remain fully compatible, as they display this version and release changelog.

4. **Git Commits & Tags**:
   - Push files to GitHub on completion.
   - Use the `github-mcp-server` (or Git/GitHub CLI) to create a GitHub Release and tag matching the new version (e.g. `v1.0.2`).
   - **CRITICAL**: Always supply detailed release notes matching the changelog description when creating the GitHub Release, as the dashboard update engine relies on this description to display update details to users.
