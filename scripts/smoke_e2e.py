"""End-to-end smoke against a real ComfyUI server with a fake Feishu messenger.

Runs `BotService.handle_text_message("/画图 ...")`, drives the task to completion,
and prints every messenger call plus the saved image paths.

Usage:
    python scripts/smoke_e2e.py [prompt]
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from comfyui_feishu.bot_service import BotService
from comfyui_feishu.comfy_client import ComfyClient
from comfyui_feishu.task_store import TaskStore
from comfyui_feishu.workflow_registry import WorkflowRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("smoke")

COMFY_URL = "http://192.168.9.101:13888"
DATA_DIR = ROOT / "data"
WORKFLOW_DIR = ROOT / "workflows"
CHAT_ID = "smoke-chat"
MESSAGE_ID = "smoke-msg"


class FakeMessenger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.images: list[Path] = []
        self._next_card_id = 1

    async def reply_text(self, message_id: str, text: str) -> None:
        self.calls.append(("reply_text", text))
        log.info("[reply_text -> %s] %s", message_id, text)

    async def send_text(self, chat_id: str, text: str) -> None:
        self.calls.append(("send_text", text))
        log.info("[send_text -> %s] %s", chat_id, text)

    async def send_image(self, chat_id: str, image_path: Path) -> None:
        self.calls.append(("send_image", str(image_path)))
        self.images.append(image_path)
        log.info("[send_image -> %s] %s (%d bytes)", chat_id, image_path, image_path.stat().st_size)

    async def reply_card(self, message_id: str, card: dict) -> str:
        cid = f"om_card_{self._next_card_id}"
        self._next_card_id += 1
        title = card["header"]["title"]["content"]
        self.calls.append(("reply_card", title))
        log.info("[reply_card -> %s] id=%s title=%s", message_id, cid, title)
        return cid

    async def send_card(self, receive_id: str, card: dict) -> str:
        cid = f"om_card_{self._next_card_id}"
        self._next_card_id += 1
        title = card["header"]["title"]["content"]
        self.calls.append(("send_card", title))
        log.info("[send_card -> %s] id=%s title=%s", receive_id, cid, title)
        return cid

    async def update_card(self, message_id: str, card: dict) -> None:
        title = card["header"]["title"]["content"]
        template = card["header"]["template"]
        self.calls.append(("update_card", template))
        log.info("[update_card -> %s] template=%s title=%s", message_id, template, title)


async def main(prompt_text: str) -> int:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)

    workflows = WorkflowRegistry.load(WORKFLOW_DIR)
    log.info("loaded workflows: %s", [w.id for w in workflows.list()])

    tasks = TaskStore(DATA_DIR / "tasks.sqlite3")
    comfy = ComfyClient(COMFY_URL)
    messenger = FakeMessenger()
    service = BotService(
        workflows=workflows,
        comfy=comfy,
        tasks=tasks,
        messenger=messenger,
        data_dir=DATA_DIR,
        progress_interval_seconds=2,
        max_concurrent_tasks=1,
    )

    text = f"/画图 txt2img {prompt_text}"
    log.info("dispatch: %s", text)
    await service.handle_text_message(CHAT_ID, MESSAGE_ID, text)

    deadline = asyncio.get_event_loop().time() + 300
    task_id: str | None = None
    while asyncio.get_event_loop().time() < deadline:
        active = [t for t in _all_tasks(tasks) if t.status not in {"succeeded", "failed", "cancelled"}]
        if active:
            task_id = active[0].task_id
        elif task_id:
            break
        await asyncio.sleep(1)

    if task_id is None:
        log.error("no task was created")
        return 1

    final = tasks.get(task_id)
    log.info("final task: %s status=%s output=%s error=%s", final.task_id, final.status, final.output_path, final.error)

    outputs_dir = DATA_DIR / "outputs" / final.task_id
    saved = list(outputs_dir.glob("*")) if outputs_dir.exists() else []
    log.info("saved files in %s: %s", outputs_dir, [p.name for p in saved])

    reply_card_count = sum(1 for c in messenger.calls if c[0] == "reply_card")
    update_card_count = sum(1 for c in messenger.calls if c[0] == "update_card")
    send_text_count = sum(1 for c in messenger.calls if c[0] == "send_text")

    log.info(
        "messenger summary: reply_card=%d update_card=%d send_image=%d send_text=%d",
        reply_card_count, update_card_count, len(messenger.images), send_text_count,
    )

    ok = (
        final.status == "succeeded"
        and bool(saved)
        and bool(messenger.images)
        and reply_card_count >= 1
        and update_card_count >= 2
        and send_text_count == 0
        and final.card_message_id is not None
    )
    log.info("RESULT: %s", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _all_tasks(store: TaskStore) -> list:
    import sqlite3

    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT task_id, status FROM tasks").fetchall()
    conn.close()

    class _T:
        def __init__(self, row):
            self.task_id = row["task_id"]
            self.status = row["status"]

    return [_T(r) for r in rows]


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or "a cute orange cat sitting on a windowsill, soft natural light, photorealistic"
    sys.exit(asyncio.run(main(prompt)))
