# Development notes

Local notes for running Murphy on a Mac with voice enabled.

## Environment

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /path/to/murphy
uv sync --group dev
unset DEEPSEEK_API_KEY   # empty shell values can block .env; prefer the repo .env
```

Put `DEEPSEEK_API_KEY=...` in a repo-local `.env` (gitignored).
`murphy` CLI loads it at startup; non-empty shell env still wins.

## Menu bar

```bash
uv run murphy menu
```

Set a project root from the menu before asking for tools.
Push to Talk Start / Stop records, transcribes with MLX Whisper, then submits text.

## MLX Whisper (STT)

Default model: `mlx-community/whisper-small-mlx` (see `config/voice.defaults.yaml`).
First launch downloads weights via Hugging Face into the HF cache.
`RuntimeController.start()` warms the model on a background thread.

## Kokoro (TTS)

Model files are **not** in the repo.
Download the kokoro-onnx v1.0 assets into Application Support:

```bash
MODEL_DIR="$HOME/Library/Application Support/Murphy/models/kokoro"
mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"
curl -L -O https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -O https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Default voice is `af_heart` (`config/voice.defaults.yaml`).
`RuntimeController` speaks confirmation prompts and final user-visible messages only (not raw tool JSON).
If the model files are missing, STT still works; status notes that TTS is unavailable.

Optional override: set `tts.model_dir` in a custom voice YAML (absolute path to the directory that contains those two files).

## Manual latency spot-checks

Placeholder checklist (fill times when you measure):

- [ ] Cold STT warmup after menu launch: ___ s
- [ ] Push-to-talk stop → transcript shown: ___ s
- [ ] Confirmation prompt TTS start after plan: ___ s
- [ ] Short result TTS ("Plan completed."): ___ s

## Tests

```bash
uv run pytest -q
```

STT and TTS unit tests mock `mlx_whisper` / `kokoro_onnx` so CI never loads real models.
