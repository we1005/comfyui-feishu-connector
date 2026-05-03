from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
import websockets

logger = logging.getLogger(__name__)


class ComfyUIError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComfyOutputFile:
    filename: str
    subfolder: str
    type: str


@dataclass(frozen=True)
class ComfyProgress:
    prompt_id: str
    status: str
    message: str
    percent: int | None = None


@dataclass(frozen=True)
class SubmittedPrompt:
    prompt_id: str
    client_id: str


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def submit_prompt(self, prompt: dict[str, Any], client_id: str | None = None) -> SubmittedPrompt:
        client_id = client_id or str(uuid.uuid4())
        payload = {"prompt": prompt, "client_id": client_id}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/prompt", json=payload)
            response.raise_for_status()
            data = response.json()

        node_errors = data.get("node_errors") or {}
        if node_errors:
            raise ComfyUIError(f"ComfyUI rejected workflow: {node_errors}")

        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"ComfyUI response missing prompt_id: {data}")

        return SubmittedPrompt(prompt_id=str(prompt_id), client_id=client_id)

    async def delete_prompt(self, prompt_id: str) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/queue", json={"delete": [prompt_id]})
            response.raise_for_status()

    async def interrupt(self) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/interrupt")
            response.raise_for_status()

    async def wait_for_prompt(
        self,
        prompt_id: str,
        client_id: str,
        poll_interval: float = 2.0,
        ws_idle_timeout: float = 60.0,
    ) -> AsyncIterator[ComfyProgress]:
        ws_url = _to_ws_url(self.base_url, f"/ws?{urlencode({'clientId': client_id})}")
        try:
            async with websockets.connect(ws_url) as websocket:
                while True:
                    raw_message = await asyncio.wait_for(websocket.recv(), timeout=ws_idle_timeout)
                    if isinstance(raw_message, bytes):
                        continue
                    event = json.loads(raw_message)
                    progress = _event_to_progress(prompt_id, event)
                    if progress is not None:
                        yield progress
                        if progress.status in {"succeeded", "failed", "cancelled"}:
                            return
        except asyncio.TimeoutError:
            logger.warning(
                "ComfyUI websocket idle for %.0fs, falling back to history polling", ws_idle_timeout
            )
        except Exception as exc:
            logger.warning("ComfyUI websocket failed, falling back to history polling: %s", exc)

        async for progress in self._poll_until_done(prompt_id, poll_interval):
            yield progress

    async def _poll_until_done(self, prompt_id: str, poll_interval: float) -> AsyncIterator[ComfyProgress]:
        while True:
            await asyncio.sleep(poll_interval)
            history = await self.get_history(prompt_id)
            if history:
                yield ComfyProgress(prompt_id=prompt_id, status="succeeded", message="ComfyUI 已完成")
                return
            yield ComfyProgress(prompt_id=prompt_id, status="running", message="ComfyUI 正在处理")

    async def get_history(self, prompt_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/history/{prompt_id}")
            response.raise_for_status()
            data = response.json()
        return data.get(prompt_id, data)

    async def download_output(self, output: ComfyOutputFile, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / output.filename
        params = {"filename": output.filename, "subfolder": output.subfolder, "type": output.type}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/view", params=params)
            response.raise_for_status()
            dest_path.write_bytes(response.content)
        return dest_path


def extract_output_files(history: dict[str, Any]) -> list[ComfyOutputFile]:
    outputs = history.get("outputs") or {}
    files: list[ComfyOutputFile] = []
    for output in outputs.values():
        for image in output.get("images") or []:
            files.append(
                ComfyOutputFile(
                    filename=str(image["filename"]),
                    subfolder=str(image.get("subfolder") or ""),
                    type=str(image.get("type") or "output"),
                )
            )
    return files


def _event_to_progress(prompt_id: str, event: dict[str, Any]) -> ComfyProgress | None:
    event_type = event.get("type")
    data = event.get("data") or {}
    event_prompt_id = data.get("prompt_id")
    if event_prompt_id and event_prompt_id != prompt_id:
        return None

    if event_type == "execution_start":
        return ComfyProgress(prompt_id, "running", "ComfyUI 开始执行")
    if event_type == "executing":
        node = data.get("node")
        if node is None:
            return ComfyProgress(prompt_id, "running", "ComfyUI 正在收尾")
        return ComfyProgress(prompt_id, "running", f"正在执行节点 {node}")
    if event_type == "progress":
        value = data.get("value")
        maximum = data.get("max")
        percent = None
        if isinstance(value, int | float) and isinstance(maximum, int | float) and maximum:
            percent = max(0, min(100, int(value / maximum * 100)))
        message = f"采样进度 {value}/{maximum}" if value is not None and maximum is not None else "ComfyUI 正在生成"
        return ComfyProgress(prompt_id, "running", message, percent)
    if event_type == "execution_success":
        return ComfyProgress(prompt_id, "succeeded", "ComfyUI 已完成")
    if event_type == "execution_error":
        exception_message = data.get("exception_message") or data.get("exception_type") or "未知错误"
        return ComfyProgress(prompt_id, "failed", f"ComfyUI 执行失败：{exception_message}")
    if event_type == "execution_interrupted":
        return ComfyProgress(prompt_id, "cancelled", "ComfyUI 任务已中断")
    return None


def _to_ws_url(base_url: str, path: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))
