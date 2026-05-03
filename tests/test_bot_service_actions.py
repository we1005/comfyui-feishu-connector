from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from comfyui_feishu.bot_service import BotService
from comfyui_feishu.task_store import TaskStore
from comfyui_feishu.workflow_registry import WorkflowRegistry


class FakeMessenger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._next_card_id = 1

    async def reply_text(self, message_id: str, text: str) -> None:
        self.calls.append(("reply_text", text))

    async def send_text(self, chat_id: str, text: str) -> None:
        self.calls.append(("send_text", text))

    async def send_image(self, chat_id: str, image_path: Path) -> None:
        self.calls.append(("send_image", str(image_path)))

    async def reply_card(self, message_id: str, card: dict[str, Any]) -> str:
        cid = f"om_card_{self._next_card_id}"
        self._next_card_id += 1
        self.calls.append(("reply_card", cid))
        return cid

    async def send_card(self, receive_id: str, card: dict[str, Any]) -> str:
        cid = f"om_card_{self._next_card_id}"
        self._next_card_id += 1
        self.calls.append(("send_card", (receive_id, card["header"]["title"]["content"])))
        return cid

    async def update_card(self, message_id: str, card: dict[str, Any]) -> None:
        self.calls.append(("update_card", (message_id, card["header"]["template"])))


class FakeComfy:
    async def delete_prompt(self, prompt_id: str) -> None:
        return None

    async def interrupt(self) -> None:
        return None


@pytest.fixture
def workflows(tmp_path: Path) -> WorkflowRegistry:
    workflow_dir = tmp_path / "wf"
    workflow_dir.mkdir()
    (workflow_dir / "txt2img.api.json").write_text(
        json.dumps({"6": {"inputs": {"text": ""}}}), encoding="utf-8"
    )
    (workflow_dir / "index.yaml").write_text(
        "workflows:\n"
        "  - id: txt2img\n"
        "    name: 文生图\n"
        "    file: txt2img.api.json\n"
        "    positive_prompt:\n"
        "      node_id: '6'\n"
        "      input: text\n",
        encoding="utf-8",
    )
    return WorkflowRegistry.load(workflow_dir)


@pytest.fixture
def service(workflows: WorkflowRegistry, tmp_path: Path) -> tuple[BotService, FakeMessenger, TaskStore]:
    messenger = FakeMessenger()
    tasks = TaskStore(tmp_path / "tasks.sqlite3")
    svc = BotService(
        workflows=workflows,
        comfy=FakeComfy(),  # type: ignore[arg-type]
        tasks=tasks,
        messenger=messenger,  # type: ignore[arg-type]
        data_dir=tmp_path / "data",
        progress_interval_seconds=1,
        max_concurrent_tasks=1,
    )
    return svc, messenger, tasks


async def test_action_status_returns_card_for_existing_task(service) -> None:
    svc, _, tasks = service
    task = tasks.create("txt2img", "cat", "chat-1", "msg-1")
    result = await svc.handle_card_action({"action": "status", "task_id": task.task_id}, "ou_x")
    assert "card" in result
    assert result["card"]["data"]["header"]["template"] == "blue"


async def test_action_status_unknown_task_toasts_error(service) -> None:
    svc, _, _ = service
    result = await svc.handle_card_action({"action": "status", "task_id": "nope"}, "ou_x")
    assert result["toast"]["type"] == "error"


async def test_action_cancel_marks_queued_task_cancelled_and_refreshes_card(service) -> None:
    svc, messenger, tasks = service
    task = tasks.create("txt2img", "cat", "chat-1", "msg-1")
    tasks.set_card_message_id(task.task_id, "om_card_1")
    result = await svc.handle_card_action({"action": "cancel", "task_id": task.task_id}, "ou_x")
    assert result["toast"]["type"] == "success"
    assert tasks.get(task.task_id).status == "cancelled"
    update_calls = [c for c in messenger.calls if c[0] == "update_card"]
    assert update_calls and update_calls[-1][1][1] == "grey"


async def test_action_regenerate_creates_new_task_and_card(service) -> None:
    svc, messenger, tasks = service
    old = tasks.create("txt2img", "a cat", "chat-1", "msg-1")
    tasks.set_done(old.task_id, "succeeded", output_paths=["x.png"])
    result = await svc.handle_card_action({"action": "regenerate", "task_id": old.task_id}, "ou_x")
    assert result["toast"]["type"] == "success"
    assert any(c[0] == "send_card" for c in messenger.calls)
    assert len(tasks.recent(limit=10)) == 2


async def test_unknown_action_returns_error_toast(service) -> None:
    svc, _, _ = service
    result = await svc.handle_card_action({"action": "wat"}, "ou_x")
    assert result["toast"]["type"] == "error"


async def test_menu_help_sends_card_to_user(service) -> None:
    svc, messenger, _ = service
    await svc.handle_menu_action("help", "ou_user_1")
    sends = [c for c in messenger.calls if c[0] == "send_card"]
    assert sends and sends[0][1][0] == "ou_user_1"
    assert "帮助" in sends[0][1][1]


async def test_menu_my_tasks_lists_recent(service) -> None:
    svc, messenger, tasks = service
    tasks.create("txt2img", "a cat", "chat-1", "msg-1")
    await svc.handle_menu_action("my_tasks", "ou_user_1")
    sends = [c for c in messenger.calls if c[0] == "send_card"]
    assert sends and "我的任务" in sends[-1][1][1]


async def test_menu_list_workflows(service) -> None:
    svc, messenger, _ = service
    await svc.handle_menu_action("list_workflows", "ou_user_1")
    sends = [c for c in messenger.calls if c[0] == "send_card"]
    assert sends and "workflow" in sends[-1][1][1].lower()


async def test_menu_unknown_event_key_is_noop(service) -> None:
    svc, messenger, _ = service
    await svc.handle_menu_action("nonexistent", "ou_user_1")
    assert not any(c[0] == "send_card" for c in messenger.calls)


async def test_handle_text_help_replies_card(service) -> None:
    svc, messenger, _ = service
    await svc.handle_text_message("chat-1", "msg-1", "/help")
    assert any(c[0] == "reply_card" for c in messenger.calls)


async def test_handle_text_list_replies_card(service) -> None:
    svc, messenger, _ = service
    await svc.handle_text_message("chat-1", "msg-1", "/画图")
    assert any(c[0] == "reply_card" for c in messenger.calls)
