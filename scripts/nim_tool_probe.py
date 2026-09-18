from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

BASE_URL = "https://integrate.api.nvidia.com/v1"
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}
MODELS = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "google/gemma-4-31b-it",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "company_registry_lookup",
            "description": (
                "Look up an organization in an authoritative company registry "
                "by organization number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "organization_number": {"type": "string"},
                },
                "required": ["organization_number"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search public web pages when an authoritative registry "
                "is not the right first source."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Search documents that are already stored in the case workspace.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

PROMPT = (
    "Finn registrert foretaksnavn for det fiktive organisasjonsnummeret 923456789. "
    "Du har ikke registerdata i konteksten. Velg og kall riktig verktøy; ikke dikt opp resultatet."
)


@dataclass
class Result:
    model: str
    transport_ok: bool
    tool_call_ok: bool
    latency_s: float
    attempts: int
    status_code: int | None = None
    selected_tool: str | None = None
    arguments: dict[str, Any] | None = None
    finish_reason: str | None = None
    error: str | None = None
    content: str = ""


def sampling(model: str) -> tuple[float, float]:
    if model.startswith("nvidia/nemotron-"):
        return 1.0, 0.95
    return 0.2, 1.0


def parse_arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def run_model(client: httpx.Client, api_key: str, model: str) -> Result:
    temperature, top_p = sampling(model)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Du er en kildekritisk norsk research-agent. Bruk verktøy når oppgaven krever "
                    "eksterne data. Ikke hevde eksterne fakta før verktøyet er kjørt."
                ),
            },
            {"role": "user", "content": PROMPT},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 256,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }
    if model.startswith("nvidia/nemotron-"):
        payload["chat_template_kwargs"] = {"enable_thinking": False}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    started = time.perf_counter()
    last_error = ""
    last_status: int | None = None

    for attempt in range(2):
        try:
            response = client.post(
                f"{BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                time.sleep(1.5)
                continue
            break

        last_status = response.status_code
        if response.status_code == 200:
            try:
                body = response.json()
                choice = body["choices"][0]
                message = choice["message"]
                calls = message.get("tool_calls") or []
                selected_tool: str | None = None
                arguments: dict[str, Any] | None = None
                if calls:
                    function = calls[0].get("function") or {}
                    selected_tool = function.get("name")
                    arguments = parse_arguments(function.get("arguments"))
                tool_call_ok = (
                    selected_tool == "company_registry_lookup"
                    and arguments is not None
                    and arguments.get("organization_number") == "923456789"
                )
                return Result(
                    model=model,
                    transport_ok=True,
                    tool_call_ok=tool_call_ok,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    status_code=200,
                    selected_tool=selected_tool,
                    arguments=arguments,
                    finish_reason=choice.get("finish_reason"),
                    content=message.get("content") or "",
                    error=None if tool_call_ok else "missing, wrong, or malformed tool call",
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                return Result(
                    model=model,
                    transport_ok=True,
                    tool_call_ok=False,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    status_code=200,
                    error=f"unexpected response shape: {exc}",
                    content=response.text[:1000],
                )

        last_error = f"HTTP {response.status_code}: {response.text[:500]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        retry_after = response.headers.get("retry-after")
        try:
            delay = min(8.0, max(1.5, float(retry_after))) if retry_after else 3.0
        except ValueError:
            delay = 3.0
        time.sleep(delay)

    return Result(
        model=model,
        transport_ok=False,
        tool_call_ok=False,
        latency_s=time.perf_counter() - started,
        attempts=2,
        status_code=last_status,
        error=last_error or "request failed",
    )


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")

    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        for model in MODELS:
            result = run_model(client, api_key, model)
            results.append(result)
            print(
                f"{model}: transport={result.transport_ok} tool={result.tool_call_ok} "
                f"selected={result.selected_tool or '-'} latency={result.latency_s:.2f}s "
                f"attempts={result.attempts} finish={result.finish_reason or '-'} "
                f"error={result.error or '-'}"
            )
            if result.arguments is not None:
                print("arguments=" + json.dumps(result.arguments, ensure_ascii=False))
            if result.content:
                print("content=" + result.content[:500].replace("\n", " "))

    os.makedirs("artifacts/nim-tool-probe", exist_ok=True)
    with open("artifacts/nim-tool-probe/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"probe": "real_openai_tool_call", "results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print("\n| Model | Transport | Tool call | Tool | Latency |")
    print("|---|---:|---:|---|---:|")
    for result in results:
        print(
            f"| `{result.model}` | {'PASS' if result.transport_ok else 'FAIL'} | "
            f"{'PASS' if result.tool_call_ok else 'FAIL'} | {result.selected_tool or '-'} | "
            f"{result.latency_s:.2f}s |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
