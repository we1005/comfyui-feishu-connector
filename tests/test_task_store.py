from comfyui_feishu.task_store import TaskStore, parse_output_paths


def test_task_lifecycle(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")

    task = store.create("txt2img", "cat", "chat", "msg")
    assert task.status == "queued"
    assert store.count_active() == 1

    store.set_started(task.task_id, "prompt", "client")
    task = store.get(task.task_id)
    assert task.status == "running"
    assert task.prompt_id == "prompt"

    store.set_progress(task.task_id, "step 1", 10)
    task = store.get(task.task_id)
    assert task.progress_message == "step 1"
    assert task.progress_percent == 10

    store.set_done(task.task_id, "succeeded", output_paths=["a.png", "b.png"])
    task = store.get(task.task_id)
    assert task.status == "succeeded"
    assert parse_output_paths(task) == ["a.png", "b.png"]
    assert store.count_active() == 0


def test_parse_output_paths_handles_legacy_plain_string(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("txt2img", "cat", "chat", "msg")
    store._update(task.task_id, status="succeeded", output_path="legacy_single.png")
    assert parse_output_paths(store.get(task.task_id)) == ["legacy_single.png"]


def test_card_message_id_persists(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("txt2img", "cat", "chat", "msg")
    assert task.card_message_id is None
    store.set_card_message_id(task.task_id, "om_abc")
    assert store.get(task.task_id).card_message_id == "om_abc"


def test_recent_returns_newest_first_and_filters_chat(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")
    a = store.create("txt2img", "1", "chat-A", "m1")
    b = store.create("txt2img", "2", "chat-B", "m2")
    c = store.create("txt2img", "3", "chat-A", "m3")
    ids_all = [t.task_id for t in store.recent(limit=10)]
    assert ids_all[0] == c.task_id and a.task_id in ids_all and b.task_id in ids_all

    ids_a = [t.task_id for t in store.recent(limit=10, chat_id="chat-A")]
    assert b.task_id not in ids_a
    assert ids_a[0] == c.task_id
