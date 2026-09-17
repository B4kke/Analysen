from __future__ import annotations

import json
import os
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
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504, 529}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "company_registry_lookup",
            "description": "Authoritative company-register lookup by organization number.",
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
            "description": "Search current public web pages for external information.",
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
            "name": "case_document_search",
            "description": "Search documents already collected into the current case.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

CASES: list[dict[str, Any]] = [
    {
        "id": "authoritative_registry",
        "prompt": (
            "Finn registrert foretaksnavn og status for org.nr. 923456789. "
            "Vi har ingen registerdata i konteksten."
        ),
        "tool": "company_registry_lookup",
        "argument_key": "organization_number",
        "argument_value": "923456789",
    },
    {
        "id": "fresh_public_web",
        "prompt": (
            "Finn den nyeste offentlige pressemeldingen på nettet om det fiktive selskapet "
            "Nordlys Eksempel AS. Den er ikke lagret i saken."
        ),
        "tool": "web_search",
        "argument_key": "query",
        "argument_contains": "Nordlys Eksempel AS",
    },
    {
        "id": "existing_case_documents",
        "prompt": (
            "Vi har allerede lastet inn 180 dokumenter i saken. Finn dokumentet som omtaler "
            "'påtroppende styreleder' uten å gjøre et nytt nettsøk."
        ),
        "tool": "case_document_search",
        "argument_key": "query",
        "argument_contains": "påtroppende styreleder",
    },
    {
        "id": "registry_over_web",
        "prompt": (
            "Bekreft den offisielt registrerte selskapsstatusen for org.nr. 908010101. "
            "Velg den mest autoritative tilgjengelige kilden."
        ),
        "tool": "company_registry_lookup",
        "argument_key": "organization_number",
        "argument_value": "908010101",
    },
    {
        "id": "no_tool_needed",
        "prompt": (
            "Ikke bruk verktøy. Regn bare ut 60 % av 70 %, og svar kort med resultatet."
        ),
        "tool": None,
    },
]


@dataclass
class Result:
    model: str
    case_id: str
    transport_ok: bool
    selected_tool: str | None
    expected_tool: str | None
    routing_correct: bool
    argument_correct: bool
    latency_s: float
    attempts: int
    error: str | None = None
    content: str = ""


def sampling(model: str) -> tuple[float, float]:
    if model.startswith("nvidia/nemotron-"):
        return 1.0, 0.95
    return 0.2, 1.0


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


def run_case(
    client: httpx.Client,
    api_key: str,
    model: str,
    case: dict[str, Any],
) -> Result:
    temperature, top_p = sampling(model)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Du er en kildekritisk research-agent. Velg riktig verktøy når eksterne "
                    "eller lagrede data kreves. Ikke bruk web hvis autoritativt register er "
                    "riktig kilde. Ikke kall verktøy når brukeren eksplisitt sier at det ikke "
                    "trengs."
                ),
            },
            {"role": "user", "content": case["prompt"]},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 280,
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
        if response.status_code == 200:
            try:
                body = response.json()
                message = body["choices"][0]["message"]
                calls = message.get("tool_calls") or []
                selected_tool: str | None = None
                args: dict[str, Any] | None = None
                if calls:
                    function = calls[0].get("function") or {}
                    selected_tool = function.get("name")
                    args = parse_args(function.get("arguments"))
                expected_tool = case["tool"]
                routing_correct = selected_tool == expected_tool
                argument_correct = routing_correct
                if expected_tool is not None:
                    argument_correct = False
                    if args is not None:
                        key = case["argument_key"]
                        value = args.get(key)
                        if "argument_value" in case:
                            argument_correct = value == case["argument_value"]
                        elif "argument_contains" in case:
                            argument_correct = (
                                isinstance(value, str)
                                and case["argument_contains"].casefold() in value.casefold()
                            )
                return Result(
                    model=model,
                    case_id=case["id"],
                    transport_ok=True,
                    selected_tool=selected_tool,
                    expected_tool=expected_tool,
                    routing_correct=routing_correct,
                    argument_correct=argument_correct,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    content=message.get("content") or "",
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = f"bad response: {exc}"
                break
        last_error = f"HTTP {response.status_code}: {response.text[:400]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        time.sleep(3.0)

    return Result(
        model=model,
        case_id=case["id"],
        transport_ok=False,
        selected_tool=None,
        expected_tool=case["tool"],
        routing_correct=False,
        argument_correct=False,
        latency_s=time.perf_counter() - started,
        attempts=2,
        error=last_error or "request failed",
    )


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")
    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(40.0, connect=10.0)) as client:
        for model in MODELS:
            for case in CASES:
                result = run_case(client, api_key, model, case)
                results.append(result)
                print(
                    f"{model} [{case['id']}] selected={result.selected_tool or 'NONE'} "
                    f"routing={result.routing_correct} args={result.argument_correct} "
                    f"latency={result.latency_s:.2f}s attempts={result.attempts} "
                    f"error={result.error or '-'}"
                )

    os.makedirs("artifacts/nim-tool-routing-stress", exist_ok=True)
    with open(
        "artifacts/nim-tool-routing-stress/results.json",
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {"results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
