import json
from typing import Any

from openai import AsyncOpenAI

from apps.api.app.core.config import Settings


class NIMProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.nim_api_key:
            raise ValueError("NIM_API_KEY is required for inference")
        self._client = AsyncOpenAI(base_url=settings.nim_base_url, api_key=settings.nim_api_key)

    async def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
            extra_body=extra_body or {},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model returned empty content")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object")
        return parsed
