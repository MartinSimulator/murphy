# Project Folder Structure

ActionIntent is the request form; ToolGateway.call is submitting that form to the right server; ToolResult is the reply. Policy decides whether you’re allowed to submit the form; the gateway only handles submission.

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
      - `gateway.py` - Three-tier policy classifier (auto_pass / confirm_required / deny)
    - `/audit` - SQLite journal of proposals, decisions, and outcomes
      - `journal.py` - AuditJournal: append ActionIntent + PolicyDecision rows to SQLite
    - `/mcp` - MCP client and sole `ToolGateway` used to call tools
    - `/execution` - Sequential runner for authorized actions
    - `/orchestrator` - LLM adapter and planning loop
    - `/workflows` - Saved offline workflows (typed tool refs, not shell strings)
    - `/voice` - Wake word, speech-to-text, and text-to-speech
    - `/ui` - macOS menu bar shell
- `/tests`
  - `test_scaffold.py` - Smoke tests that the package, CLI, paths, and config files exist
  - `test_policy_decisions.py` - Decision-table tests for policy tiers, schema rejection, and audit journal

## Tests:
To run the test suite, run the following commands in order
`export PATH="$HOME/.local/bin:$PATH"`
`uv sync --group dev`
`uv run pytest -v`

## Notes:
* The reason for the policy folder is because LLM judgement and Speech-To-Text is not trustworthy. Since LLMs can be wrong, we assign risk tiers deterministically.
* Schemas (schema.py and config/schemas/): We use these to validate args before an ActionIntent object is created. The orchestrator proposes tool calls but doesn't construct an intent by itself
* Sequencing multiple tool calls lives in executor.py, not ToolGateway
* Auditing (journal.py): records proposals, confirmations, and outcomes 
* General Flow:
  - The user speaks an activation word (**"murphy"**) -> identified using openWakeWord -> Murphy enters a listening state where speech is transcribed to text via STT
  - The orchestrator (DeepSeek) proposes a tool call where build_validated_action_intent in schema.py validates against JSON schemas to construct frozen ActionIntents (sometimes a list of ActionIntents rather than just one)
  - The execute_actions method in executor.py runs that list calling classify (gateway.py) for each intent, assigning it auto_pass, confirm_required, or deny, journaling the decision
  - If the classification is deny, we journal it, stop the plan, cancel the tool call
  - If the classification is confirm_required, we run ConfirmationStore.create in tool_gateway.py to add a pending verification to the dict. The TTS will ask the long prompt about the tool call / risk and the user must say the required tokens ("confirm" + "tool"). One clarification is allowed if there's a phrase mismatch.
  - If the classification is auto_pass or a confirmed confirm_required, we run ToolGateway.call(intent) which actually calls the MCP server for that intent returning whether it was properly executed or if it failed
  - Executor returns a PlanResult (steps, completed?, why stoped?, optional pending) and the TTS will tell the user what happened
