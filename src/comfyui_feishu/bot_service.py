from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Protocol

from comfyui_feishu.card_builder import (
    build_help_card,
    build_my_tasks_card,
    build_progress_card,
    build_workflow_list_card,
)
from comfyui_feishu.commands import HELP_TEXT, CommandType, parse_command
from comfyui_feishu.comfy_client import ComfyClient, ComfyUIError, extract_output_files
from comfyui_feishu.task_store import Task, TaskStore, format_task
from comfyui_feishu.translator import Translator
from comfyui_feishu.workflow_registry import WorkflowConfigError, WorkflowRegistry

logger = logging.getLogger(__name__)


class Messenger(Protocol):
    async def reply_text(self, message_id: str, text: str) -> None: ...
    async def send_text(self, chat_id: str, text: str) -> None: ...
    async def send_image(self, chat_id: str, image_path: Path) -> None: ...
    async def reply_card(self, message_id: str, card: dict[str, Any]) -> str: ...
    async def send_card(self, chat_id: str, card: dict[str, Any]) -> str: ...
    async def update_card(self, message_id: str, card: dict[str, Any]) -> None: ...


class BotService:
    def __init__(
        self,
        workflows: WorkflowRegistry,
        comfy: ComfyClient,
        tasks: TaskStore,
        messenger: Messenger,
        data_dir: Path,
        progress_interval_seconds: int,
        max_concurrent_tasks: int,
        translator: Translator | None = None,
    ) -> None:
        self.workflows = workflows
        self.comfy = comfy
        self.tasks = tasks
        self.messenger = messenger
        self.output_dir = data_dir / "outputs"
        self.progress_interval_seconds = progress_interval_seconds
        self.max_concurrent_tasks = max_concurrent_tasks
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self.translator = translator

    # ---- text command entry ----

    async def handle_text_message(self, chat_id: str, message_id: str, text: str) -> None:
        command = parse_command(text)
        logger.info("recv text chat=%s msg=%s type=%s text=%r", chat_id, message_id, command.type, text)

        if command.type == CommandType.HELP:
            await self.messenger.reply_card(message_id, build_help_card())
            return

        if command.type == CommandType.LIST_WORKFLOWS:
            await self.messenger.reply_card(message_id, build_workflow_list_card(self.workflows.list()))
            return

        if command.type == CommandType.DRAW:
            assert command.workflow_id is not None
            assert command.prompt is not None
            await self._handle_draw(chat_id, message_id, command.workflow_id, command.prompt)
            return

        if command.type == CommandType.STATUS:
            assert command.task_id is not None
            await self._handle_status(message_id, command.task_id)
            return

        if command.type == CommandType.CANCEL:
            assert command.task_id is not None
            await self._handle_cancel(message_id, command.task_id)
            return

        await self.messenger.reply_text(message_id, HELP_TEXT)

    # ---- card action callback ----

    async def handle_card_action(self, action_value: dict[str, Any], operator_open_id: str | None) -> dict[str, Any]:
        action = action_value.get("action")
        task_id = action_value.get("task_id")

        if action == "cancel" and task_id:
            return await self._action_cancel(task_id)
        if action == "status" and task_id:
            return self._action_status(task_id)
        if action == "regenerate" and task_id:
            return await self._action_regenerate(task_id, operator_open_id)
        return {"toast": {"type": "error", "content": "未知操作"}}

    async def _action_cancel(self, task_id: str) -> dict[str, Any]:
        try:
            task = self.tasks.get(task_id)
        except KeyError:
            return {"toast": {"type": "error", "content": f"未找到任务 {task_id}"}}

        if task.status not in {"queued", "running"}:
            return {"toast": {"type": "info", "content": f"任务当前状态 {task.status}，无需取消"}}

        if task.status == "running":
            if task.prompt_id:
                await self.comfy.delete_prompt(task.prompt_id)
            await self.comfy.interrupt()

        self.tasks.set_done(task_id, "cancelled", error="用户取消")
        await self._refresh_task_card(task_id)
        return {"toast": {"type": "success", "content": "已取消任务"}}

    def _action_status(self, task_id: str) -> dict[str, Any]:
        try:
            task = self.tasks.get(task_id)
        except KeyError:
            return {"toast": {"type": "error", "content": f"未找到任务 {task_id}"}}
        return {"card": {"type": "raw", "data": _card_for_task(task, self.workflows)}}

    async def _action_regenerate(self, task_id: str, _operator_open_id: str | None) -> dict[str, Any]:
        try:
            old = self.tasks.get(task_id)
        except KeyError:
            return {"toast": {"type": "error", "content": f"未找到任务 {task_id}"}}
        try:
            workflow = self.workflows.get(old.workflow_id)
        except WorkflowConfigError as exc:
            return {"toast": {"type": "error", "content": str(exc)}}

        new_task = self.tasks.create(workflow.spec.id, old.prompt_text, old.chat_id, old.message_id)
        card = build_progress_card(
            task_id=new_task.task_id,
            workflow_name=workflow.spec.name,
            prompt_text=old.prompt_text,
            status="queued",
        )
        new_card_id = await self.messenger.send_card(old.chat_id, card)
        self.tasks.set_card_message_id(new_task.task_id, new_card_id)
        asyncio.create_task(self._run_task(new_task.task_id))
        return {"toast": {"type": "success", "content": f"已提交新任务 {new_task.task_id}"}}

    # ---- bot menu callback ----

    async def handle_menu_action(self, event_key: str, operator_open_id: str | None) -> None:
        if not operator_open_id:
            logger.warning("menu event without operator open_id")
            return

        if event_key == "list_workflows":
            await self._send_card_to_user(operator_open_id, build_workflow_list_card(self.workflows.list()))
            return
        if event_key == "my_tasks":
            recent = self.tasks.recent(limit=10)
            await self._send_card_to_user(operator_open_id, build_my_tasks_card(recent))
            return
        if event_key == "help":
            await self._send_card_to_user(operator_open_id, build_help_card())
            return

        logger.warning("unknown menu event_key: %s", event_key)

    async def _send_card_to_user(self, open_id: str, card: dict[str, Any]) -> None:
        await self.messenger.send_card(open_id, card)

    # ---- draw / run ----

    async def _handle_draw(self, chat_id: str, message_id: str, workflow_id: str, prompt_text: str) -> None:
        try:
            workflow = self.workflows.get(workflow_id)
        except WorkflowConfigError as exc:
            await self.messenger.reply_text(message_id, f"{exc}")
            await self.messenger.reply_card(message_id, build_workflow_list_card(self.workflows.list()))
            return

        task = self.tasks.create(workflow.spec.id, prompt_text, chat_id, message_id)
        card = build_progress_card(
            task_id=task.task_id,
            workflow_name=workflow.spec.name,
            prompt_text=prompt_text,
            status="queued",
        )
        card_message_id = await self.messenger.reply_card(message_id, card)
        self.tasks.set_card_message_id(task.task_id, card_message_id)
        asyncio.create_task(self._run_task(task.task_id))

    async def _handle_status(self, message_id: str, task_id: str) -> None:
        try:
            task = self.tasks.get(task_id)
        except KeyError:
            await self.messenger.reply_text(message_id, f"未找到任务：{task_id}")
            return
        await self.messenger.reply_text(message_id, format_task(task))

    async def _handle_cancel(self, message_id: str, task_id: str) -> None:
        try:
            task = self.tasks.get(task_id)
        except KeyError:
            await self.messenger.reply_text(message_id, f"未找到任务：{task_id}")
            return

        if task.status == "queued":
            self.tasks.set_done(task_id, "cancelled", error="用户取消")
            await self._refresh_task_card(task_id)
            await self.messenger.reply_text(message_id, f"已取消任务 {task_id}")
            return

        if task.status == "running":
            if task.prompt_id:
                await self.comfy.delete_prompt(task.prompt_id)
            await self.comfy.interrupt()
            self.tasks.set_done(task_id, "cancelled", error="用户取消")
            await self._refresh_task_card(task_id)
            await self.messenger.reply_text(message_id, f"已请求中断任务 {task_id}")
            return

        await self.messenger.reply_text(message_id, f"任务 {task_id} 当前状态为 {task.status}，无需取消。")

    async def _run_task(self, task_id: str) -> None:
        async with self.semaphore:
            task = self.tasks.get(task_id)
            if task.status == "cancelled":
                await self._refresh_task_card(task_id)
                return

            try:
                workflow = self.workflows.get(task.workflow_id)
                prompt_text = task.prompt_text
                if self.translator is not None:
                    prompt_text = await self.translator.to_english(prompt_text)
                    if prompt_text != task.prompt_text:
                        logger.info("translated task %s -> %r", task_id, prompt_text)
                prompt = workflow.build_prompt(prompt_text)
                submitted = await self.comfy.submit_prompt(prompt)
                self.tasks.set_started(task_id, submitted.prompt_id, submitted.client_id)
                await self._refresh_task_card(task_id)

                last_update = 0.0
                async for progress in self.comfy.wait_for_prompt(submitted.prompt_id, submitted.client_id):
                    self.tasks.set_progress(task_id, progress.message, progress.percent)
                    now = time.monotonic()
                    if now - last_update >= self.progress_interval_seconds:
                        await self._refresh_task_card(task_id)
                        last_update = now
                    if progress.status == "failed":
                        self.tasks.set_done(task_id, "failed", error=progress.message)
                        await self._refresh_task_card(task_id)
                        return
                    if progress.status == "cancelled":
                        self.tasks.set_done(task_id, "cancelled", error=progress.message)
                        await self._refresh_task_card(task_id)
                        return

                await self._send_outputs(task_id)
            except Exception as exc:
                logger.exception("task failed: %s", task_id)
                self.tasks.set_done(task_id, "failed", error=str(exc))
                await self._refresh_task_card(task_id)

    async def _send_outputs(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task.prompt_id:
            raise ComfyUIError("task has no ComfyUI prompt_id")

        history = await self.comfy.get_history(task.prompt_id)
        outputs = extract_output_files(history)
        if not outputs:
            raise ComfyUIError("ComfyUI history 中没有找到输出图片")

        saved_paths: list[str] = []
        for output in outputs:
            image_path = await self.comfy.download_output(output, self.output_dir / task_id)
            saved_paths.append(str(image_path))
            await self.messenger.send_image(task.chat_id, image_path)

        self.tasks.set_done(task_id, "succeeded", output_paths=saved_paths)
        await self._refresh_task_card(task_id)

    async def _refresh_task_card(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task.card_message_id:
            return
        card = _card_for_task(task, self.workflows)
        try:
            await self.messenger.update_card(task.card_message_id, card)
        except Exception:
            logger.exception("failed to update card for task %s", task_id)


def _card_for_task(task: Task, workflows: WorkflowRegistry) -> dict[str, Any]:
    try:
        workflow_name = workflows.get(task.workflow_id).spec.name
    except WorkflowConfigError:
        workflow_name = task.workflow_id
    image_count: int | None = None
    if task.status == "succeeded":
        from comfyui_feishu.task_store import parse_output_paths

        image_count = len(parse_output_paths(task))
    return build_progress_card(
        task_id=task.task_id,
        workflow_name=workflow_name,
        prompt_text=task.prompt_text,
        status=task.status,
        progress_message=task.progress_message,
        progress_percent=task.progress_percent,
        image_count=image_count,
        error=task.error,
    )
