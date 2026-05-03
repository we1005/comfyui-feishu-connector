from comfyui_feishu.comfy_client import ComfyOutputFile, _to_ws_url, extract_output_files


def test_extract_output_files() -> None:
    history = {
        "outputs": {
            "9": {
                "images": [
                    {"filename": "a.png", "subfolder": "", "type": "output"},
                    {"filename": "b.png", "subfolder": "x", "type": "temp"},
                ]
            }
        }
    }

    assert extract_output_files(history) == [
        ComfyOutputFile(filename="a.png", subfolder="", type="output"),
        ComfyOutputFile(filename="b.png", subfolder="x", type="temp"),
    ]


def test_to_ws_url() -> None:
    assert _to_ws_url("http://127.0.0.1:8188", "/ws?clientId=1") == "ws://127.0.0.1:8188/ws?clientId=1"
    assert _to_ws_url("https://example.com/api", "/ws?clientId=1") == "wss://example.com/ws?clientId=1"
