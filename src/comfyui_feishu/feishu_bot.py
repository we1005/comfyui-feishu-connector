from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from comfyui_feishu.bot_service import BotService

logger = logging.getLogger(__name__)


class FeishuMessenger:
    def __init__(self, app_id: str, app_secret: str) -> None:
        import lark_oapi as lark

        self._lark = lark
        self.client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

    async def reply_text(self, message_id: str, text: str) -> None:
        await asyncio.to_thread(self._reply_text_sync, message_id, text)

    async def send_text(self, chat_id: str, text: str) -> None:
        await asyncio.to_thread(self._send_text_sync, chat_id, text)

    async def send_image(self, chat_id: str, image_path: Path) -> None:
        image_key = await asyncio.to_thread(self._upload_image_sync, image_path)
        await asyncio.to_thread(self._send_image_sync, chat_id, image_key)

    async def reply_card(self, message_id: str, card: dict[str, Any]) -> str:
        return await asyncio.to_thread(self._reply_card_sync, message_id, card)

    async def send_card(self, receive_id: str, card: dict[str, Any]) -> str:
        """Send an interactive card. receive_id may be chat_id or open_id (auto-detected)."""
        return await asyncio.to_thread(self._send_card_sync, receive_id, card)

    async def update_card(self, message_id: str, card: dict[str, Any]) -> None:
        await asyncio.to_thread(self._update_card_sync, message_id, card)

    def _reply_text_sync(self, message_id: str, text: str) -> None:
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.reply(request)
        _raise_for_lark_response(response)

    def _send_text_sync(self, chat_id: str, text: str) -> None:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        _raise_for_lark_response(response)

    def _upload_image_sync(self, image_path: Path) -> str:
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

        with image_path.open("rb") as image_file:
            request = (
                CreateImageRequest.builder()
                .request_body(CreateImageRequestBody.builder().image_type("message").image(image_file).build())
                .build()
            )
            response = self.client.im.v1.image.create(request)
        _raise_for_lark_response(response)
        image_key = getattr(response.data, "image_key", None)
        if not image_key:
            raise RuntimeError(f"Feishu image upload response missing image_key: {response}")
        return str(image_key)

    def _send_image_sync(self, chat_id: str, image_key: str) -> None:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("image")
                .content(json.dumps({"image_key": image_key}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        _raise_for_lark_response(response)

    def _reply_card_sync(self, message_id: str, card: dict[str, Any]) -> str:
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.reply(request)
        _raise_for_lark_response(response)
        return _extract_message_id(response)

    def _send_card_sync(self, receive_id: str, card: dict[str, Any]) -> str:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        receive_id_type = "open_id" if receive_id.startswith("ou_") else "chat_id"
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        _raise_for_lark_response(response)
        return _extract_message_id(response)

    def _update_card_sync(self, message_id: str, card: dict[str, Any]) -> None:
        from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                PatchMessageRequestBody.builder().content(json.dumps(card, ensure_ascii=False)).build()
            )
            .build()
        )
        response = self.client.im.v1.message.patch(request)
        _raise_for_lark_response(response)


class FeishuLongConnectionBot:
    def __init__(self, app_id: str, app_secret: str, service: BotService) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.service = service

    def start(self) -> None:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        from lark_oapi.api.application.v6.model.p2_application_bot_menu_v6 import P2ApplicationBotMenuV6
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            CallBackToast,
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
        from lark_oapi.ws import Client as WsClient

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, name="feishu-bot-loop", daemon=True)
        loop_thread.start()

        def _log_future_exception(label: str):
            def _cb(fut):
                exc = fut.exception()
                if exc is not None:
                    logger.error("%s failed: %r", label, exc)
            return _cb

        def on_message(event: P2ImMessageReceiveV1) -> None:
            try:
                chat_id, message_id, text = _extract_message(event)
            except ValueError as exc:
                logger.info("ignore unsupported Feishu event: %s", exc)
                return
            fut = asyncio.run_coroutine_threadsafe(
                self.service.handle_text_message(chat_id, message_id, text), loop
            )
            fut.add_done_callback(_log_future_exception("handle_text_message"))

        def on_card_action(event: P2CardActionTrigger) -> P2CardActionTriggerResponse:
            data = event.event
            value = (data.action.value if data and data.action else None) or {}
            open_id = data.operator.open_id if data and data.operator else None
            future = asyncio.run_coroutine_threadsafe(
                self.service.handle_card_action(value, open_id), loop
            )
            try:
                result = future.result(timeout=10)
            except Exception:
                logger.exception("card action handler failed")
                return _build_card_response(P2CardActionTriggerResponse, CallBackToast, CallBackCard, {"toast": {"type": "error", "content": "处理失败"}})
            return _build_card_response(P2CardActionTriggerResponse, CallBackToast, CallBackCard, result)

        def on_bot_menu(event: P2ApplicationBotMenuV6) -> None:
            data = event.event
            event_key = data.event_key if data else None
            open_id = (
                data.operator.operator_id.open_id
                if data and data.operator and data.operator.operator_id
                else None
            )
            if not event_key:
                logger.info("bot menu event missing event_key")
                return
            fut = asyncio.run_coroutine_threadsafe(
                self.service.handle_menu_action(event_key, open_id), loop
            )
            fut.add_done_callback(_log_future_exception("handle_menu_action"))

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .register_p2_card_action_trigger(on_card_action)
            .register_p2_application_bot_menu_v6(on_bot_menu)
            .build()
        )

        lark_level = getattr(lark.LogLevel, logging.getLevelName(logger.getEffectiveLevel()), lark.LogLevel.INFO)
        ws_client = WsClient(self.app_id, self.app_secret, event_handler=event_handler, log_level=lark_level)
        logger.info("starting Feishu long-connection client")
        ws_client.start()


def _build_card_response(response_cls, toast_cls, card_cls, result: dict[str, Any]):
    response = response_cls()
    toast = result.get("toast") if isinstance(result, dict) else None
    card = result.get("card") if isinstance(result, dict) else None
    if toast:
        t = toast_cls()
        t.type = toast.get("type")
        t.content = toast.get("content")
        response.toast = t
    if card:
        c = card_cls()
        c.type = card.get("type", "raw")
        c.data = card.get("data")
        response.card = c
    return response


def _extract_message(event: Any) -> tuple[str, str, str]:
    message = event.event.message
    if message.message_type != "text":
        raise ValueError(f"unsupported message type: {message.message_type}")

    content = json.loads(message.content or "{}")
    text = content.get("text")
    if not text:
        raise ValueError("empty text message")

    text = _strip_mentions(str(text), getattr(message, "mentions", None))
    if not text:
        raise ValueError("empty text after stripping mentions")

    chat_id = getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    if not chat_id or not message_id:
        raise ValueError("message missing chat_id or message_id")

    return str(chat_id), str(message_id), text


def _strip_mentions(text: str, mentions: Any) -> str:
    if mentions:
        for mention in mentions:
            key = getattr(mention, "key", None)
            if key:
                text = text.replace(key, "")
    return text.strip()


def _extract_message_id(response: Any) -> str:
    data = getattr(response, "data", None)
    message_id = getattr(data, "message_id", None) if data is not None else None
    if not message_id:
        raise RuntimeError(f"Feishu API response missing message_id: {response}")
    return str(message_id)


def _raise_for_lark_response(response: Any) -> None:
    success = getattr(response, "success", None)
    if callable(success):
        ok = success()
    else:
        code = getattr(response, "code", 0)
        ok = code == 0
    if ok:
        return

    code = getattr(response, "code", "unknown")
    msg = getattr(response, "msg", "unknown")
    raw = getattr(response, "raw", None)
    body = None
    if raw is not None:
        content = getattr(raw, "content", None)
        if isinstance(content, (bytes, bytearray)):
            try:
                body = content.decode("utf-8", errors="replace")[:500]
            except Exception:
                body = None
        elif isinstance(content, str):
            body = content[:500]
    raise RuntimeError(f"Feishu API failed: code={code}, msg={msg}, body={body}")
