from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODELS = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "google/gemma-4-31b-it",
]
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "company_registry_lookup",
            "description": "Fetch authoritative synthetic company register data by org number.",
            "parameters": {
                "type": "object",
                "properties": {"organization_number": {"type": "string"}},
                "required": ["organization_number"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search public pages for secondary information.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]
TOOL_RESULT = {
    "organization_number": "923456789",
    "organization": "Skjærgårdsforvaltning Øst AS",
    "register_updated": "2026-09-16",
    "roles": [
        {
            "role": "styreleder",
            "person": "Åse Ødegård",
            "from": "2025-05-15",
            "to": None,
            "status": "active",
        },
        {
            "role": "styreleder",
            "person": "Bjørn Sæther",
            "from": "2023-02-01",
            "to": "2025-05-14",
            "status": "ended",
        },
    ],
}


@dataclass
class Result:
    model: str
    first_transport_ok: bool
    correct_tool: bool
    second_transport_ok: bool
    final_json_ok: bool
    final_exact_fields: int
    total_fields: int
    first_latency_s: float
    second_latency_s: float
    first_attempts: int
    second_attempts: int
    error: str | None = None
    final_output: str = ""


def model_sampling(model: str) -> tuple[float, float]:
    if model.startswith("nvidia/nemotron-"):
        return 1.0, 0.95
    return 0.2, 1.0


def request(
    client: httpx.Client,
    api_key: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, float, int, str | None]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    started = time.perf_counter()
    last_error = ""
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
            return None, time.perf_counter() - started, attempt + 1, last_error
        if response.status_code == 200:
            try:
                return (
                    response.json(),
                    time.perf_counter() - started,
                    attempt + 1,
                    None,
                )
            except ValueError as exc:
                error = f"invalid response JSON: {exc}"
                return None, time.perf_counter() - started, attempt + 1, error
        last_error = f"HTTP {response.status_code}: {response.text[:400]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            return None, time.perf_counter() - started, attempt + 1, last_error
        time.sleep(3.0)
    return None, time.perf_counter() - started, 2, last_error or "request failed"


def parse_args(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates = [stripped]
    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        candidates.append(fenced.group(1))
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def run_model(client: httpx.Client, api_key: str, model: str) -> Result:
    temperature, top_p = model_sampling(model)
    system = (
        "Du er en kildekritisk research-agent. Bruk autoritativt register før web når "
        "brukeren spør om registrerte selskapsroller. Ikke dikt opp registerdata."
    )
    user = (
        "For det fiktive org.nr. 923456789: hvem er registrert styreleder per "
        "17.09.2026, og når tiltrådte personen? Bruk riktig verktøy først."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    first_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": 300,
        "stream": False,
    }
    if model.startswith("nvidia/nemotron-"):
        first_payload["chat_template_kwargs"] = {"enable_thinking": False}

    first_body, first_latency, first_attempts, first_error = request(
        client,
        api_key,
        first_payload,
    )
    if first_body is None:
        return Result(
            model=model,
            first_transport_ok=False,
            correct_tool=False,
            second_transport_ok=False,
            final_json_ok=False,
            final_exact_fields=0,
            total_fields=3,
            first_latency_s=first_latency,
            second_latency_s=0.0,
            first_attempts=first_attempts,
            second_attempts=0,
            error=first_error,
        )

    try:
        assistant_message = first_body["choices"][0]["message"]
        calls = assistant_message.get("tool_calls") or []
        call = calls[0] if calls else None
        function = call.get("function") if call else None
        name = function.get("name") if function else None
        args = parse_args(function.get("arguments")) if function else None
        correct_tool = (
            name == "company_registry_lookup"
            and args is not None
            and args.get("organization_number") == "923456789"
        )
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        return Result(
            model=model,
            first_transport_ok=True,
            correct_tool=False,
            second_transport_ok=False,
            final_json_ok=False,
            final_exact_fields=0,
            total_fields=3,
            first_latency_s=first_latency,
            second_latency_s=0.0,
            first_attempts=first_attempts,
            second_attempts=0,
            error=f"bad first response: {exc}",
        )

    if not correct_tool or call is None:
        return Result(
            model=model,
            first_transport_ok=True,
            correct_tool=False,
            second_transport_ok=False,
            final_json_ok=False,
            final_exact_fields=0,
            total_fields=3,
            first_latency_s=first_latency,
            second_latency_s=0.0,
            first_attempts=first_attempts,
            second_attempts=0,
            error="wrong or missing first tool call",
        )

    messages.append(assistant_message)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": "company_registry_lookup",
            "content": json.dumps(TOOL_RESULT, ensure_ascii=False),
        }
    )
    messages.append(
        {
            "role": "user",
            "content": (
                "Svar nå kun med JSON: chair, chair_since og source_updated. "
                "Datoer skal være YYYY-MM-DD."
            ),
        }
    )
    second_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": 350,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if model.startswith("nvidia/nemotron-"):
        second_payload["chat_template_kwargs"] = {"enable_thinking": False}

    second_body, second_latency, second_attempts, second_error = request(
        client,
        api_key,
        second_payload,
    )
    if second_body is None:
        return Result(
            model=model,
            first_transport_ok=True,
            correct_tool=True,
            second_transport_ok=False,
            final_json_ok=False,
            final_exact_fields=0,
            total_fields=3,
            first_latency_s=first_latency,
            second_latency_s=second_latency,
            first_attempts=first_attempts,
            second_attempts=second_attempts,
            error=second_error,
        )

    try:
        output = (second_body["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        output = ""
        second_error = f"bad second response: {exc}"
    parsed = extract_json(output)
    expected = {
        "chair": "Åse Ødegård",
        "chair_since": "2025-05-15",
        "source_updated": "2026-09-16",
    }
    hits = 0
    if parsed is not None:
        for key, value in expected.items():
            if str(parsed.get(key, "")).strip().casefold() == value.casefold():
                hits += 1

    return Result(
        model=model,
        first_transport_ok=True,
        correct_tool=True,
        second_transport_ok=True,
        final_json_ok=parsed is not None,
        final_exact_fields=hits,
        total_fields=3,
        first_latency_s=first_latency,
        second_latency_s=second_latency,
        first_attempts=first_attempts,
        second_attempts=second_attempts,
        error=second_error,
        final_output=output,
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
                f"{model}: tool={result.correct_tool} final="
                f"{result.final_exact_fields}/{result.total_fields} "
                f"latency={result.first_latency_s:.2f}+{result.second_latency_s:.2f}s "
                f"attempts={result.first_attempts}+{result.second_attempts} "
                f"error={result.error or '-'}"
            )
            if result.final_output:
                print(result.final_output[:700].replace("\n", " "))

    os.makedirs("artifacts/nim-agent-loop", exist_ok=True)
    with open("artifacts/nim-agent-loop/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
