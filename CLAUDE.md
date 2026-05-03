# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Feishu (Lark) long-connection bot that takes draw commands from Feishu chat, runs them through a local ComfyUI instance, and posts progress + generated images back to the chat. The Chinese product spec is in `需求.md` and the build plan in `实施计划.md`.

## Common commands

```bash
# Install (editable, with dev extras) into a venv
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the bot (reads .env via pydantic-settings; or `set -a; source .env; set +a` first)
comfyui-feishu

# Tests
pytest                              # all
pytest tests/test_commands.py       # single file
pytest tests/test_commands.py::test_parse_draw_command   # single test
```

There is no linter/formatter configured. `pyproject.toml` sets `asyncio_mode = "auto"` so async tests don't need `@pytest.mark.asyncio`.

## Architecture

The runtime is composed in `main.py` and follows a layered design — keep new code on the right layer rather than reaching across.

1. **`config.py` — `Settings`**: pydantic-settings model that reads `.env`. Only place that knows about env vars; everything else takes plain values.
2. **`workflow_registry.py`**: loads `workflows/index.yaml` plus the referenced ComfyUI API-format JSONs once at startup. Each `WorkflowSpec` declares `NodeInputRef`s (node_id + input_name) for `positive_prompt`, `negative_prompt`, `seed`, `width`, `height`. `Workflow.build_prompt(text)` deep-copies the JSON and patches those nodes (random seed if `randomize: true`). The schema is validated against the JSON at load time, so a misconfigured `index.yaml` fails fast on startup, not on the first user command.
3. **`comfy_client.py` — `ComfyClient`**: thin async wrapper over ComfyUI's HTTP API (`/api/prompt`, `/api/queue`, `/api/interrupt`, `/api/history/{id}`, `/api/view`) plus the `/ws` websocket. `wait_for_prompt` is an async generator that yields `ComfyProgress` events translated from raw ComfyUI ws events; if the websocket fails it falls back to polling `/api/history`. `extract_output_files` walks the history JSON to recover output image refs.
4. **`task_store.py` — `TaskStore`**: SQLite-backed task table at `<DATA_DIR>/tasks.sqlite3`. Tasks transition `queued → running → {succeeded|failed|cancelled}`. `count_active()` is what enforces `MAX_CONCURRENT_TASKS` — bumping concurrency requires both raising the env var and ensuring the semaphore in `BotService` is sized accordingly (it is, via the same setting).
5. **`bot_service.py` — `BotService`**: the orchestrator. `handle_text_message` dispatches by `CommandType`; `_handle_draw` admits the task and spawns `_run_task` via `asyncio.create_task`. `_run_task` is gated by `asyncio.Semaphore(max_concurrent_tasks)`, drives the comfy client, throttles progress messages by `progress_interval_seconds`, and on success calls `_send_outputs` which downloads each output to `<DATA_DIR>/outputs/<task_id>/` and uploads to Feishu. Cancellation: queued tasks are flipped in-store; running tasks call `delete_prompt` + `interrupt` on ComfyUI.
6. **`feishu_bot.py`**: two classes. `FeishuMessenger` implements the `Messenger` Protocol from `bot_service` using `lark_oapi`'s sync API wrapped in `asyncio.to_thread` (image send is two calls: upload → get `image_key` → send). `FeishuLongConnectionBot.start()` runs the lark websocket client on the main thread and pushes incoming events to a dedicated asyncio loop running in a daemon thread via `asyncio.run_coroutine_threadsafe` — this is the bridge between lark's blocking ws client and the otherwise-async service.
7. **`commands.py`**: pure parser for Chinese-prefixed commands (`/画图`, `/状态`, `/取消`, plus `/help`). No I/O; trivial to unit-test.

The `Messenger` Protocol in `bot_service.py` is the seam used in tests — `BotService` never imports `lark_oapi` directly.

## Adding a workflow

1. In ComfyUI, enable Settings → Dev Mode Options, then `Save (API Format)` to export the prompt JSON. UI-format JSON will not work.
2. Drop the file in `workflows/` and add an entry in `workflows/index.yaml`. Each `node_id` is the string key in the API JSON; `input` is the field on `inputs`. `_validate_prompt` will reject any ref that doesn't resolve.
3. Optional refs (`negative_prompt`, `seed`, `width`, `height`) are only patched when present on the spec; `seed.randomize: true` regenerates a 63-bit int per task.

## Feishu app requirements

Long-connection (websocket) event mode must be enabled. Required scopes: `im.message.receive_v1` event subscription, plus `im:message`, `im:message:send_as_bot`, `im:resource` permissions. Set `FEISHU_APP_ID` / `FEISHU_APP_SECRET` in `.env`.
