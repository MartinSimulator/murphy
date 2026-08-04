**Concept**  
Murphy is a voice-controlled orchestration layer for developer workflows. It sits above your existing tools (editor, terminal, containers, version control) and lets you drive multi-step tasks with natural language, coordinating across apps that don't otherwise talk to each other (e.g. "set up the dev environment" spinning up Docker, opening the project in Cursor, and arranging a WezTerm session in one command).

Under the hood, Murphy is an MCP client. It  connects to an MCP server for each tool and uses an LLM's tool-calling ability to turn spoken commands into the right sequence of calls. A deterministic policy layer sits between every proposed call and its execution, independent of the LLM's own judgment, and flags anything destructive or hard to reverse (git push \--force, rm \-rf, docker system prune) for explicit confirmation before it runs.

Murphy runs as a lightweight background app (menu bar / tray) listening for the "Murphy" wake word, and responds with either confirmation that a command completed or a clarifying question when a command is flagged. It doesn't write or edit code — that's still your editor's job. Its job is everything around the code.

Murphy is the MCP client. Each integration (Cursor, Docker, WezTerm, git, Spotify) is a separate MCP server, either adopted from an existing open-source implementation or written in-house where none exists. The policy engine sits inside the client, between the model's proposed tool call and the dispatch to any server — this is the one component that must never be bypassed.

**Purpose**  
Coding agents like Cursor operate inside a single editor, on that editor's own terminal/file/browser access. Murphy operates above individual apps — coordinating Cursor, a terminal multiplexer, Docker, and git as separate tools that don't know about each other, with a confirmation gate that lives outside any one of them. It is not trying to write code better than an editor's built-in agent; it is trying to remove the manual choreography of switching between and setting up multiple tools, and to catch destructive actions before they execute regardless of which tool proposed them.

**Goals**

* Cross-App Orchestration: One natural-language command can trigger coordinated actions across editor, terminal, containers, and VCS.  
* Deterministic Safety Gate: Destructive/irreversible actions require explicit human confirmation, enforced outside the LLM’s own reasoning.   
* Low Friction on Safe Operations: Safe, additive, or read-only actions execute immediately with no interruption.  
* Auditability: Every proposed and executed action is logged with risk tier and outcome.  
* Voice-First but not Voice-Only: Wake-word voice control is the primary interface; text input works identically as a fall-back for alternate environments like quiet spaces. 

**Non-Goals**

* Murphy does not write, refactor, or edit source code. That stays in the editor.  
* Murphy does not replace Cursor/VSCode's own in-editor agent — it composes with them, not competes.  
* v1 does not target non-Mac/UNIX environments or deep IntelliJ integration.  
* Murphy is a local, single-user tool for v1, not a multi-user product.

**Technology Stack**

| LLM (orchestration brain) | DeepSeek V4 Flash (cloud) using Anthropic-compatible url | \~9x cheaper than Claude and 2-3x faster per-token which is critical for voice UX |
| :---- | :---- | :---- |
| Client Protocol | MCP (Model Context Protocol) | Use Anthropic’s MCP SDK |
| Terminal Control | WezTerm MCP server | Don’t rebuild pane control, WezTerm already has this |
| Containers | Docker MCP server (wrapper over Docker CLI/API) | Simple, well-documented |
| Version Control | Git MCP server (wrapper over git CLI) | Same rationale as Docker |
| Editor | Cursor CLI | Deliberately shallow integration (open the app, open a folder, not deep editor control) |
| Music | Spotify Web API MCP server | Playback control (play, pause, skip); low risk tool by nature so all commands auto-pass |
| Wake Word | openWakeWord | Fully open-source, easy Python integration |
| Speech-to-Text | Whisper (local) | Avoid sending everything to a cloud API |
| Text-to-Speech | Kokoro-82M (local) | Lightweight, CPU-only, high-quality sound |
| Policy Engine | Custom Python scripts | Deterministic regex/AST pattern matching and config-driven risk tiers. No ML. |
| Background App/UI Shell | Menu bar / tray app (macOS first) | Minimal; status icon, start/stop, log viewer |
| Audit log | Local structured log (JSON lines or SQLite) | Every proposed \+ executed action, risk tier, outcome, timestamp |

**Core Components**

* Orchestrator (MCP Client)  
  * Owns the conversation loop with DeepSeek  
  * Discovers tools from all connected MCP servers at startup  
  * Routes every model-proposed tool call through the policy engine before dispatch  
  * Accepts input from either the voice pipeline or a text channel with identical handling  
* Policy Engine (Main Security System)  
  * Deterministic (not LLM based)  
  * Config-driven risk classification \- pattern match on command strings, scope check on file/dir targets, per-tool override tiers  
  * Three-tiered output: auto-pass, confirm-required, deny (deny reserved for small hard-blocked set)  
  * Deny (hard-blocked, no override): commands targeting `/`, `~`, `/etc`, or any path outside the active project root.  
* Confirmation Flow  
  * On confirm-required, orchestrator pauses the tool-call loop and surfaces a question to the user (voice and/or text)  
  * Response (yes/no/modified command) is fed back into the loop  
  * Designed to match the shape of MCP’s native elicitation primitive so Murphy’s servers can later be reused by other MCP clients without redesigning this layer  
* Audit Log  
  * Append-only record of every proposed action (command, tool, risk tier, decision, timestamp, outcome)  
  * Serves as both a debugging tool and a trust artifact for demo  
* Voice Layer  
  * Wake word detector runs continuously, low resource footprint  
  * On activation: record → Whisper transcription → text handed to orchestrator exactly as if typed  
  * TTS responses for confirmations and clarifying questions; text log always available as fallback  
* Menu Bar App  
  * Status Indicator (idle/listening/awaiting confirmation)  
  * Start/stop toggle  
  * Log viewer for the audit trail  
  * Deliberately minimal for version 1

**Security Model**   
Since the LLM has execution access, the main security risks involve prompt injection, hallucination, or ambiguous voice transcription which all could cause the model to take destructive action. Therefore, mitigation is a central part of this project. 

1. The policy engine is deterministic rather than a model call: No prompt can talk the policy engine into reclassifying a command’s risk tier since the model is never asked  
2. The gate sits at the client, not inside individual servers: Every tool call from every server passes through the policy layer so a new integration doesn’t get to opt out  
3. Risks tiers are config, not hardcoded: They are auditable and adjustable without affecting orchestrator logic  
4. Scope is enforced independently of intent: A command targeting a path outside the active project directory is treated as higher risk regardless of the command itself

**Example Scenarios**

| Scenario | Behavior |
| :---- | :---- |
| “Set up project A by opening Cursor, WezTerm cd’d into the project repo, and start postgres” | All calls auto-pass; multi-app setup completes with no interruptions |
| “Spin up the test container and run the test suite” | Docker compose up and test run, both auto-pass |
| “Commit this and push” (feature branch and no force) | Auto-passes \- low-risk branch, non-destructive |
| “Push to main” or \- \- force required | Flagged \- orchestrator asks for explicit confirmation before proceeding |
| “Clean up the docker mess and prune everything”  | Docker system prune \-a \- \- volume flagged as high-risk/broad scope; orchestrator asks to confirm or offers to scope to the current project only |
| “Pause project A, open project B” | Cross-context switch \- WezTerm session for project A persists in the background, Cursor opens project B |

