from dataclasses import dataclass

from comfyui_feishu.feishu_bot import _strip_mentions


@dataclass
class _Mention:
    key: str


def test_strip_mentions_removes_bot_at_prefix() -> None:
    text = "@_user_1 /画图 txt2img 一只猫"
    assert _strip_mentions(text, [_Mention("@_user_1")]) == "/画图 txt2img 一只猫"


def test_strip_mentions_handles_multiple_and_no_mentions() -> None:
    text = "@_user_1 hi @_user_2"
    assert _strip_mentions(text, [_Mention("@_user_1"), _Mention("@_user_2")]) == "hi"
    assert _strip_mentions("/画图", None) == "/画图"
    assert _strip_mentions("/画图", []) == "/画图"


def test_strip_mentions_preserves_internal_whitespace_in_prompt() -> None:
    text = "@_user_1 /画图 txt2img a  cat"
    assert _strip_mentions(text, [_Mention("@_user_1")]) == "/画图 txt2img a  cat"
