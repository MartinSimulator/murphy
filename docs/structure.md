# Project Folder Structure

- `pyproject.toml` - Package metadata, Python 3.12, CLI entry point, pytest config, dependencies
- `uv.lock` - Locked dependency versions for reproducible installs
- `.python-version` - Pins the project to Python 3.12 for uv
- `/docs`
  - `design-doc.md` - High-level project overview: goals, security model, and example scenarios
  - `structure.md` - Map of the repository layout and what each part is for
- `/config` - Checked-in safe defaults (user secrets and mutable state live under Application Support)
  - `policy.defaults.yaml` - Default risk tiers, deny roots, and protected branches for the policy gateway
  - `mcp.servers.yaml` - Which MCP integrations exist and how they are launched (stdio)
  - `/schemas` - JSON Schemas for each narrow tool (`git.push.json`, `docker.prune.json`, ...)
- `/src`
  - `/murphy` - Installable application package
    - `__init__.py` - Package version and public identity
    - `cli.py` - `murphy` CLI entry point (help and version today)
    - `paths.py` - Runtime user-data location (`~/Library/Application Support/Murphy/`)
    - `/app` - Runtime state machine (`idle`, `listening`, `executing`, ...)
    - `/policy` - Deterministic auto-pass / confirm / deny gate
      - `intent.py` - ActionIntent model and canonical digest (content fingerprint) for action identity
      - `schema.py` - Validate tool arguments against checked-in JSON Schemas before an ActionIntent is built
    - `/audit` - SQLite journal of proposals, decisions, and outcomes

    - `/mcp` - MCP client and sole `ToolGateway` used to call tools
    - `/execution` - Sequential runner for authorized actions
    - `/orchestrator` - LLM adapter and planning loop
    - `/workflows` - Saved offline workflows (typed tool refs, not shell strings)
    - `/voice` - Wake word, speech-to-text, and text-to-speech
    - `/ui` - macOS menu bar shell
- `/tests`
  - `test_scaffold.py` - Smoke tests that the package, CLI, paths, and config files exist

