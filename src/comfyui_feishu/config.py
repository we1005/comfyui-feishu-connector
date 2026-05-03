from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    feishu_app_id: str = Field(..., alias="FEISHU_APP_ID")
    feishu_app_secret: SecretStr = Field(..., alias="FEISHU_APP_SECRET")
    feishu_bot_name: str = Field(default="ComfyUI Bot", alias="FEISHU_BOT_NAME")

    comfyui_base_url: str = Field(default="http://192.168.9.101:13888", alias="COMFYUI_BASE_URL")
    workflow_dir: Path = Field(default=Path("./workflows"), alias="WORKFLOW_DIR")
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    progress_interval_seconds: int = Field(default=5, ge=1, alias="PROGRESS_INTERVAL_SECONDS")
    max_concurrent_tasks: int = Field(default=1, ge=1, alias="MAX_CONCURRENT_TASKS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    dashscope_api_key: SecretStr | None = Field(default=None, alias="DASHSCOPE_API_KEY")
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="DASHSCOPE_BASE_URL",
    )
    translator_model: str = Field(default="qwen-plus", alias="TRANSLATOR_MODEL")

    @property
    def tasks_db_path(self) -> Path:
        return self.data_dir / "tasks.sqlite3"
