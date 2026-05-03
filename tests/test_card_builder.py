from comfyui_feishu.card_builder import (
    build_help_card,
    build_my_tasks_card,
    build_progress_card,
    build_workflow_list_card,
)
from comfyui_feishu.task_store import Task
from comfyui_feishu.workflow_registry import NodeInputRef, WorkflowSpec


def _spec(id_: str = "txt2img", desc: str = "") -> WorkflowSpec:
    return WorkflowSpec(
        id=id_,
        name="文生图",
        description=desc,
        file=f"{id_}.json",
        positive_prompt=NodeInputRef(node_id="6", input_name="text"),
    )


def test_progress_card_running_has_cancel_and_status_buttons() -> None:
    card = build_progress_card(
        task_id="t1",
        workflow_name="文生图",
        prompt_text="a cat",
        status="running",
        progress_message="采样进度 5/15",
        progress_percent=33,
    )
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    assert "🎨" in card["header"]["title"]["content"]
    actions = card["body"]["elements"][-1]["actions"]
    labels = [a["text"]["content"] for a in actions]
    assert labels == ["取消任务", "查看状态"]
    assert {"action": "cancel", "task_id": "t1"} in [a["value"] for a in actions]
    bar = next(e for e in card["body"]["elements"] if e["tag"] == "progress_bar")
    assert bar["percent"] == 33


def test_progress_card_succeeded_only_regenerate() -> None:
    card = build_progress_card(
        task_id="t1",
        workflow_name="文生图",
        prompt_text="a cat",
        status="succeeded",
        image_count=2,
    )
    assert card["header"]["template"] == "green"
    actions = card["body"]["elements"][-1]["actions"]
    assert [a["text"]["content"] for a in actions] == ["重画一张"]
    assert any("共生成" in e.get("content", "") for e in card["body"]["elements"] if e["tag"] == "markdown")


def test_progress_card_failed_shows_error() -> None:
    card = build_progress_card(
        task_id="t1",
        workflow_name="文生图",
        prompt_text="a cat",
        status="failed",
        error="OOM",
    )
    assert card["header"]["template"] == "red"
    assert any("OOM" in e.get("content", "") for e in card["body"]["elements"] if e["tag"] == "markdown")


def test_progress_card_truncates_long_prompt() -> None:
    long_prompt = "a " * 200
    card = build_progress_card(
        task_id="t1", workflow_name="w", prompt_text=long_prompt, status="queued"
    )
    body_text = card["body"]["elements"][0]["content"]
    assert "…" in body_text


def test_workflow_list_card_lists_specs_and_handles_empty() -> None:
    card = build_workflow_list_card([_spec("a", desc="A"), _spec("b")])
    text = card["body"]["elements"][0]["content"]
    assert "**a**" in text and "**b**" in text and "A" in text
    empty = build_workflow_list_card([])
    assert "暂无可用 workflow" in empty["body"]["elements"][0]["content"]


def test_help_card_has_command_list() -> None:
    card = build_help_card()
    text = card["body"]["elements"][0]["content"]
    assert "/画图" in text and "/状态" in text and "/取消" in text


def test_my_tasks_card_lists_recent_with_status_emoji() -> None:
    tasks = [
        Task(
            task_id="t1",
            workflow_id="txt2img",
            prompt_text="a cute orange cat sitting in a sunny field with flowers",
            chat_id="c",
            message_id="m",
            status="succeeded",
            output_path='["a.png", "b.png"]',
        ),
        Task(
            task_id="t2",
            workflow_id="txt2img",
            prompt_text="dog",
            chat_id="c",
            message_id="m",
            status="failed",
        ),
    ]
    card = build_my_tasks_card(tasks)
    text = card["body"]["elements"][0]["content"]
    assert "t1" in text and "t2" in text
    assert "✅" in text and "❌" in text
    assert "2 张" in text

    empty = build_my_tasks_card([])
    assert "还没有提交过任务" in empty["body"]["elements"][0]["content"]
