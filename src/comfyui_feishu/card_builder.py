"""Builders for Feishu interactive cards (JSON 2.0 schema).

Pure functions returning dicts. No lark dependency, easy to unit-test.
"""
from __future__ import annotations

from typing import Any

from comfyui_feishu.task_store import Task, parse_output_paths
from comfyui_feishu.workflow_registry import WorkflowSpec


_PROMPT_PREVIEW_LIMIT = 80
_TEMPLATE_BY_STATUS = {
    "queued": ("blue", "🕒", "排队中"),
    "running": ("blue", "🎨", "生成中"),
    "succeeded": ("green", "✅", "已完成"),
    "failed": ("red", "❌", "失败"),
    "cancelled": ("grey", "⏹️", "已取消"),
}


def build_progress_card(
    task_id: str,
    workflow_name: str,
    prompt_text: str,
    status: str,
    progress_message: str | None = None,
    progress_percent: int | None = None,
    image_count: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    template, emoji, label = _TEMPLATE_BY_STATUS.get(status, _TEMPLATE_BY_STATUS["queued"])

    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": (
                f"**Workflow** {workflow_name}\n"
                f"**任务 ID** `{task_id}`\n"
                f"**提示词** {_truncate(prompt_text, _PROMPT_PREVIEW_LIMIT)}"
            ),
        }
    ]

    if status == "running":
        pct = progress_percent if progress_percent is not None else 0
        elements.append({"tag": "markdown", "content": _ascii_progress(pct)})
        if progress_message:
            elements.append({"tag": "markdown", "content": f"`{progress_message}`"})

    if status == "succeeded" and image_count:
        elements.append({"tag": "markdown", "content": f"🖼️ 共生成 **{image_count}** 张图，已发送到聊天。"})

    if status in {"failed", "cancelled"} and error:
        elements.append({"tag": "markdown", "content": f"⚠️ {error}"})

    elements.append({"tag": "hr"})
    elements.append(_build_action_row(task_id, status))

    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{emoji} ComfyUI · {label}"},
            "template": template,
        },
        "body": {"elements": elements},
    }


def _build_action_row(task_id: str, status: str) -> dict[str, Any]:
    if status in {"queued", "running"}:
        buttons = [
            _button("取消任务", "danger", {"action": "cancel", "task_id": task_id}),
            _button("查看状态", "default", {"action": "status", "task_id": task_id}),
        ]
    else:
        buttons = [_button("重画一张", "primary", {"action": "regenerate", "task_id": task_id})]
    return _row_columns(buttons)


def _row_columns(buttons: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "columns": [
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [b]} for b in buttons
        ],
    }


def _button(text: str, button_type: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "value": value,
    }


def build_workflow_list_card(specs: list[WorkflowSpec]) -> dict[str, Any]:
    if not specs:
        elements: list[dict[str, Any]] = [
            {"tag": "markdown", "content": "暂无可用 workflow。请检查 `workflows/index.yaml`。"}
        ]
    else:
        lines = ["**可用 workflow：**"]
        for spec in specs:
            extra = f" — {spec.description}" if spec.description else ""
            lines.append(f"- **{spec.id}** · {spec.name}{extra}")
        lines.append("")
        lines.append("使用方式：`/画图 <workflow_id> <提示词>`")
        elements = [{"tag": "markdown", "content": "\n".join(lines)}]

    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🎨 画图 workflow 列表"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_help_card() -> dict[str, Any]:
    content = (
        "**ComfyUI 飞书机器人**\n\n"
        "**命令：**\n"
        "- `/画图` — 列出可用 workflow\n"
        "- `/画图 <workflow_id> <提示词>` — 提交生成任务\n"
        "- `/状态 <task_id>` — 查询任务状态\n"
        "- `/取消 <task_id>` — 取消任务\n\n"
        "**提示：** 群聊里需要 @ 机器人；提交后会发一张可刷新的卡片，"
        "点卡片上的按钮即可取消、查看或重画。"
    )
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "ℹ️ 帮助"},
            "template": "turquoise",
        },
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }


def build_my_tasks_card(tasks: list[Task]) -> dict[str, Any]:
    if not tasks:
        elements: list[dict[str, Any]] = [{"tag": "markdown", "content": "你还没有提交过任务。"}]
    else:
        lines = ["**最近任务：**", ""]
        for task in tasks:
            status_emoji = _TEMPLATE_BY_STATUS.get(task.status, _TEMPLATE_BY_STATUS["queued"])[1]
            preview = _truncate(task.prompt_text, 40)
            paths = parse_output_paths(task)
            tail = f" · {len(paths)} 张" if paths else ""
            lines.append(f"{status_emoji} `{task.task_id}` · {task.workflow_id} · {preview}{tail}")
        elements = [{"tag": "markdown", "content": "\n".join(lines)}]

    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📋 我的任务"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _ascii_progress(percent: int, width: int = 20) -> str:
    p = max(0, min(100, int(percent)))
    filled = int(round(p / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"`{bar} {p}%`"
