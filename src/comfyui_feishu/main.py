from __future__ import annotations

import logging

import truststore

# Use the OS trust store (macOS Keychain / Windows cert store / Linux CA bundle)
# so corporate / MITM root CAs are trusted. Must run before any TLS connection.
truststore.inject_into_ssl()

from comfyui_feishu.bot_service import BotService  # noqa: E402
from comfyui_feishu.comfy_client import ComfyClient  # noqa: E402
from comfyui_feishu.config import Settings  # noqa: E402
from comfyui_feishu.feishu_bot import FeishuLongConnectionBot, FeishuMessenger  # noqa: E402
from comfyui_feishu.logging_config import configure_logging  # noqa: E402
from comfyui_feishu.task_store import TaskStore  # noqa: E402
from comfyui_feishu.translator import Translator  # noqa: E402
from comfyui_feishu.workflow_registry import WorkflowRegistry  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    workflows = WorkflowRegistry.load(settings.workflow_dir)
    tasks = TaskStore(settings.tasks_db_path)
    comfy = ComfyClient(settings.comfyui_base_url)
    messenger = FeishuMessenger(settings.feishu_app_id, settings.feishu_app_secret.get_secret_value())

    translator: Translator | None = None
    if settings.dashscope_api_key is not None:
        translator = Translator(
            api_key=settings.dashscope_api_key.get_secret_value(),
            base_url=settings.dashscope_base_url,
            model=settings.translator_model,
        )
        logger.info("translator enabled (model=%s)", settings.translator_model)
    else:
        logger.info("translator disabled (no DASHSCOPE_API_KEY)")

    service = BotService(
        workflows=workflows,
        comfy=comfy,
        tasks=tasks,
        messenger=messenger,
        data_dir=settings.data_dir,
        progress_interval_seconds=settings.progress_interval_seconds,
        max_concurrent_tasks=settings.max_concurrent_tasks,
        translator=translator,
    )

    logger.info("loaded %s workflows", len(workflows.list()))
    FeishuLongConnectionBot(settings.feishu_app_id, settings.feishu_app_secret.get_secret_value(), service).start()


if __name__ == "__main__":
    main()
