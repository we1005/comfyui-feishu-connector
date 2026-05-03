import json

import yaml

from comfyui_feishu.workflow_registry import WorkflowRegistry


def test_load_and_build_prompt(tmp_path) -> None:
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir()
    prompt = {
        "3": {"inputs": {"seed": 1}},
        "5": {"inputs": {"width": 512, "height": 512}},
        "6": {"inputs": {"text": ""}},
        "7": {"inputs": {"text": ""}},
    }
    (workflow_dir / "txt2img.api.json").write_text(json.dumps(prompt), encoding="utf-8")
    (workflow_dir / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "workflows": [
                    {
                        "id": "txt2img",
                        "name": "文生图",
                        "file": "txt2img.api.json",
                        "positive_prompt": {"node_id": "6", "input": "text"},
                        "negative_prompt": {"node_id": "7", "input": "text", "default": "bad"},
                        "seed": {"node_id": "3", "input": "seed", "default": 42},
                        "width": {"node_id": "5", "input": "width", "default": 1024},
                        "height": {"node_id": "5", "input": "height", "default": 768},
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    registry = WorkflowRegistry.load(workflow_dir)
    built = registry.get("txt2img").build_prompt("cat")

    assert built["6"]["inputs"]["text"] == "cat"
    assert built["7"]["inputs"]["text"] == "bad"
    assert built["3"]["inputs"]["seed"] == 42
    assert built["5"]["inputs"]["width"] == 1024
    assert built["5"]["inputs"]["height"] == 768
    assert prompt["6"]["inputs"]["text"] == ""
