# Project Folder Structure

ActionIntent is the request form; ToolGateway.call is submitting that form to the right server; ToolResult is the reply.
Policy decides whether you’re allowed to submit the form; the gateway only handles submission.

- `pyproject.toml` - Package metadata, Python 3.12, CLI entry point, pytest config, dependencies
- `uv.lock` - Locked dependency versions for reproducible installs
- `.python-version` - Pins the project to Python 3.12 for uv
- `/docs`
  - `design-doc.md` - High-level project overview: goals, security model, and example scenarios
  - `structure.md` - Map of the repository layout and what each part is for
- `/config` - Checked-in safe defaults (user secrets and mutable state live under Application Support)
  - `policy.defaults.yaml` - Default risk tiers, deny roots, and protected branches for the policy gateway
  - `side_effects.yaml` - Default impact class per `server.tool` (`read-only` / `additive` / `mutative` / `destructive`)
  - `llm.defaults.yaml` - DeepSeek V4 Flash URL, model name, timeout, and API key reference
  - `voice.defaults.yaml` - Local STT (MLX Whisper) and TTS placeholders
  - `mcp.servers.yaml` - Which MCP integrations exist and how they are launched (stdio)
  - `/schemas` - JSON Schemas for each narrow tool (`git.push.json`, `docker.prune.json`, ...)
- `/src`
  - `/murphy` - Installable application package
    - `__init__.py` - Package version and public identity
    - `cli.py` - `murphy` CLI entry point with murphy ask and subparsers for args
    - `paths.py` - Runtime user-data location (`~/Library/Application Support/Murphy/`)
    - `/app` - Runtime state machine and coordinator (`idle`, `listening`, `executing`, ...)
      - `state.py` - `AppState`, handlers protocol, `AppStateMachine`
      - `state_handlers/` - Allowed transitions per state
      - `settings.py` - Load/save `project_root` under Application Support
      - `runtime.py` - `RuntimeController`: worker-thread `handle_text`, confirmation Event
    - `/policy` - Deterministic auto-pass / confirm / deny gate
      - `intent.py` - ActionIntent model and canonical digest (content fingerprint) for action identity
      - `schema.py` - Validate tool arguments against checked-in JSON Schemas before an ActionIntent is built
      - `side_effects.py` - Look up `SideEffect` for a `server.tool` from `side_effects.yaml`
      - `gateway.py` - Three-tier policy classifier (auto_pass / confirm_required / deny)
    - `/audit` - SQLite journal of proposals, decisions, and outcomes
      - `journal.py` - AuditJournal: append ActionIntent + PolicyDecision rows to SQLite
    - `/mcp` - MCP client and sole `ToolGateway` used to call tools
      - `tool_gateway.py` - track MCP server availability and dispatch calls
      - `/fake_handlers` - In-process git/docker fakes used by `murphy ask` and tests
    - `/execution` - Sequential runner for authorized actions
      - `confirmation.py` - Holds confirm_required ActionIntents and defines what confirms a request
      - `executor.py` - Classify ActionIntents and dispatch tools to the ToolGateway
      - `run_ask.py` - Wires CLI args from subparsers into handle_text (in router.py)
    - `/orchestrator` - DeepSeek V4 Flash planning loop (LLM proposes; policy still gates)
      - `llm.py` - Shared contract: `ToolProposal`, `LLMRequest`, `LLMResponse`, `LLMClient` protocol, LLM errors
      - `fake_llm.py` - Scripted `LLMClient` for tests (no network); exact / substring / default responses
      - `config.py` - Load and cache LLM settings from llm.defaults.yaml
      - `deepseek.py` - Build, send, and parse messages between Murphy and DeepSeek
      - `planner.py` - Ask the LLM for tool calls, validate them, and return ActionIntents.
      - `router.py` - Text facade: `handle_text` runs `plan` then `execute_actions` and returns `HandleResult`
      - `tools_for_prompt.py` - Build the tool list to send to the LLM for planning
    - `/voice` - Wake word, speech-to-text, and text-to-speech
      - `capture.py` - Push-to-talk mic capture (`AudioCapture`, `FakeAudioCapture`)
      - `stt.py` - `Transcriber` protocol; `MlxWhisperTranscriber` (MLX Whisper)
      - `config.py` - Load STT/TTS defaults from `config/voice.defaults.yaml`
    - `/ui` - macOS menu bar shell (PyObjC)
      - `menu_app.py` - `NSStatusItem` menu; posts to `RuntimeController` only
      - `log_viewer.py` - Scrollable audit log window from `fetch_recent`
      - `run_menu.py` - Entry used by `murphy menu`
- `/tests`
  - `test_scaffold.py` - Smoke tests that the package, CLI, paths, and config files exist
  - `test_policy_decisions.py` - Decision-table tests for policy tiers, schema rejection, and audit journal
  - `test_side_effects.py` - Side-effect catalog load and `side_effect_for` lookup
  - `test_llm.py` - LLM contract models and `LLMClient` protocol smoke tests
  - `test_fake_llm.py` - FakeLLM exact / substring / default / unavailable behavior
  - `test_orchestrator_config.py` - LLM config load and API key resolution
  - `test_tools_for_prompt.py` - Schema catalog to prompt tool defs
  - `test_planner.py` - Planner builds validated intents via FakeLLM
  - `test_deepseek.py` - DeepSeek client with mocked HTTP
  - `test_router.py` - `handle_text` facade wiring
  - `test_cli_ask.py` - `murphy ask` CLI wiring
  - `test_text_e2e.py` - Text E2E LLM paths (auto-pass, confirm, deny, schema fail, unavailable)
  - `test_app_state.py` - AppStateMachine transitions and handlers
  - `test_runtime.py` - RuntimeController worker thread and confirmation
  - `test_menu.py` - Menu helpers, fetch_recent, macOS import smoke
  - `test_tool_gateway.py` - ToolGateway lifecycle and fake handlers
  - `test_confirmation.py` - Digest-bound confirmation phrases
  - `test_executor.py` - Sequential execution and policy gating

## Tests:
To run the test suite, run the following commands in order
`export PATH="$HOME/.local/bin:$PATH"`
`uv sync --group dev`
`uv run pytest -v`

## Notes:
* The reason for the policy folder is because LLM judgement and Speech-To-Text is not trustworthy.
  Since LLMs can be wrong, we assign risk tiers deterministically.
* Schemas (`schema.py` and `config/schemas/`): We use these to validate args before an ActionIntent object is created.
  The orchestrator proposes tool calls but doesn't construct an intent by itself.
* Side effects (`side_effects.py` and `config/side_effects.yaml`): Impact labels on the ActionIntent (and digest/audit).
  Separate from policy tiers; the LLM must not invent them.
* `llm.py` is only the interface.
  `fake_llm.py` stubs DeepSeek in tests; `deepseek.py` is the real HTTP client.
* Sequencing multiple tool calls lives in `executor.py`, not ToolGateway.
* Auditing (`journal.py`): records proposals, confirmations, and outcomes.
* General Flow:
  - Today (text): `murphy ask "..."` → `run_ask` → `handle_text` (same planning/execution path as below)
  - Later (voice): The user speaks an activation word (**"murphy"**) -> identified using openWakeWord -> Murphy enters a listening state where speech is transcribed to text via STT
  - The orchestrator (DeepSeek V4 Flash, or FakeLLM in tests) returns ordered `ToolProposal`s
  - Each proposal is turned into an ActionIntent via `side_effect_for` + `build_validated_action_intent` (schema validation)
  - The `execute_actions` method in `executor.py` runs that list calling `classify` (`gateway.py`) for each intent, assigning it auto_pass, confirm_required, or deny, journaling the decision
  - If the classification is deny, we journal it, stop the plan, cancel the tool call
  - If the classification is confirm_required, we run `ConfirmationStore.create` to add a pending verification.
    The TTS will ask the long prompt about the tool call / risk and the user must say the required tokens ("confirm" + "tool").
    One clarification is allowed if there's a phrase mismatch.
  - If the classification is auto_pass or a confirmed confirm_required, we run `ToolGateway.call(intent)` which actually calls the MCP server for that intent returning whether it was properly executed or if it failed
  - Executor returns a PlanResult (steps, completed?, why stopped?, optional pending) and the TTS will tell the user what happened

## How is Input Handled
1. begin_ptt (in runtime controller) opens the mic with AudioCapture.start and moves state to LISTENING
2. end_ptt stops the capture, moves the state to TRANSCRIBING, and starts murphy-ptt-finish which calls AudioCapture.stop() which concatenates chunks into a float32 array
3. a different thread (murphy-ptt-finish) transcribes those samples using mlx-whisper (injected)
4. if it was a new ask, it goes back to IDLE and calls submit_text(text) which is when the handle-text worker starts
5. if PTT was for a pending_confirmation, it calls submit_confirmation_phrase(text) instead and doesn't go through handle_text again
Mental Model for Typical Scenarios: mic -> numpy arr -> STT -> text -> submit_text -> worker -> handle_text -> plan -> execute