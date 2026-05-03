from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommandType(StrEnum):
    HELP = "help"
    LIST_WORKFLOWS = "list_workflows"
    DRAW = "draw"
    STATUS = "status"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Command:
    type: CommandType
    workflow_id: str | None = None
    prompt: str | None = None
    task_id: str | None = None
    raw: str = ""


HELP_TEXT = (
    "可用命令：\n"
    "/画图 - 查看可用 workflow\n"
    "/画图 <workflow_id> <提示词> - 生成图片\n"
    "/状态 <task_id> - 查询任务状态\n"
    "/取消 <task_id> - 取消任务"
)


def parse_command(text: str) -> Command:
    raw = _normalize(text).strip()
    if not raw:
        return Command(CommandType.UNKNOWN, raw=text)

    if raw in {"/help", "help", "帮助", "/帮助"}:
        return Command(CommandType.HELP, raw=text)

    if raw == "/画图":
        return Command(CommandType.LIST_WORKFLOWS, raw=text)

    if raw.startswith("/画图 "):
        _, rest = raw.split(" ", 1)
        parts = rest.strip().split(maxsplit=1)
        if len(parts) < 2:
            return Command(CommandType.UNKNOWN, raw=text)
        return Command(CommandType.DRAW, workflow_id=parts[0], prompt=parts[1].strip(), raw=text)

    if raw.startswith("/状态 "):
        task_id = raw.split(maxsplit=1)[1].strip()
        return Command(CommandType.STATUS, task_id=task_id, raw=text)

    if raw.startswith("/取消 "):
        task_id = raw.split(maxsplit=1)[1].strip()
        return Command(CommandType.CANCEL, task_id=task_id, raw=text)

    return Command(CommandType.UNKNOWN, raw=text)


def _normalize(text: str) -> str:
    return text.replace("／", "/").replace("　", " ")
