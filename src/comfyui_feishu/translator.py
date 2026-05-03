"""Chinese → English prompt translation via DashScope (OpenAI-compatible API).

The hosted SDXL/Juggernaut models in this project use OpenAI's CLIP, which
does not understand Chinese. We translate the user's Chinese prompt into
English before submitting to ComfyUI; the original text is kept for display.
"""
from __future__ import annotations

import logging
import re

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_HAN_RE = re.compile(r"[一-鿿]")

_SYSTEM_PROMPT = (
    "You translate Chinese image-generation prompts into English. "
    "Output ONLY the English translation as a single line of comma-separated "
    "descriptive phrases suitable for an SDXL CLIP text encoder. "
    "Preserve every visual detail (subject, pose, lighting, mood, camera, "
    "style). Do not add commentary, quotes, or markdown. "
    "If the input is already English, return it unchanged."
)


class Translator:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def to_english(self, text: str) -> str:
        if not _HAN_RE.search(text):
            return text
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
                extra_body={"enable_thinking": False},
            )
            out = (resp.choices[0].message.content or "").strip()
            if not out:
                logger.warning("translator returned empty; falling back to original")
                return text
            return out
        except Exception:
            logger.exception("translation failed; falling back to original prompt")
            return text
