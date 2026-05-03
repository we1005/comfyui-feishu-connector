from comfyui_feishu.commands import CommandType, parse_command


def test_parse_list_workflows() -> None:
    command = parse_command("/画图")

    assert command.type == CommandType.LIST_WORKFLOWS


def test_parse_draw_command() -> None:
    command = parse_command("/画图 txt2img 一只赛博朋克猫")

    assert command.type == CommandType.DRAW
    assert command.workflow_id == "txt2img"
    assert command.prompt == "一只赛博朋克猫"


def test_parse_status_command() -> None:
    command = parse_command("/状态 abc123")

    assert command.type == CommandType.STATUS
    assert command.task_id == "abc123"


def test_parse_cancel_command() -> None:
    command = parse_command("/取消 abc123")

    assert command.type == CommandType.CANCEL
    assert command.task_id == "abc123"


def test_parse_accepts_fullwidth_slash_and_space() -> None:
    command = parse_command("／画图　txt2img　一只猫")

    assert command.type == CommandType.DRAW
    assert command.workflow_id == "txt2img"
    assert command.prompt == "一只猫"


def test_parse_list_workflows_with_fullwidth_slash() -> None:
    assert parse_command("／画图").type == CommandType.LIST_WORKFLOWS
