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
REPEATS = 4
CASES: list[dict[str, Any]] = [
    {
        "id": "double_negative",
        "prompt": (
            "Tekst: 'Det er ikke riktig at selskapet aldri har hatt ansatte.' "
            "Returner KUN JSON med has_had_employees som true, false eller null."
        ),
        "expected": {"has_had_employees": True},
    },
    {
        "id": "simple_negation_role",
        "prompt": (
            "Tekst: 'Kari Testperson er ikke daglig leder. Hun er registrert som "
            "styremedlem.' Returner KUN JSON med is_manager og documented_role."
        ),
        "expected": {"is_manager": False, "documented_role": "styremedlem"},
    },
    {
        "id": "incoming_vs_current",
        "prompt": (
            "Tekst: 'Bjørn Sæther er sittende styreleder. Åse Ødegård er påtroppende "
            "styreleder og overtar 1. oktober.' Returner KUN JSON med current_chair og "
            "incoming_chair."
        ),
        "expected": {
            "current_chair": "Bjørn Sæther",
            "incoming_chair": "Åse Ødegård",
        },
    },
]


@dataclass
class Result:
    model: str
    case_id: str
    repeat: int
    transport_ok: bool
    json_ok: bool
    correct: bool
    latency_s: float
    attempts: int
    error: str | None = None
    output: str = ""


def sampling(model: str) -> tuple[float, float]:
    if model.startswith("nvidia/nemotron-"):
        return 1.0, 0.95
    return 0.2, 1.0


def equal(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return actual is expected
    return str(actual).strip().casefold() == str(expected).strip().casefold()


def run_once(
    client: httpx.Client,
    api_key: str,
    model: str,
    case: dict[str, Any],
    repeat: int,
) -> Result:
    temperature, top_p = sampling(model)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Les norsk bokstavelig. Følg negasjon og tidsstatus presist. "
                    "Ikke forklar. Svar kun med gyldig JSON."
                ),
            },
            {"role": "user", "content": case["prompt"]},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 300,
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
                time.sleep(1.0)
                continue
            break
        if response.status_code == 200:
            try:
                body = response.json()
                output = (body["choices"][0]["message"].get("content") or "").strip()
                parsed = json.loads(output)
                if not isinstance(parsed, dict):
                    raise TypeError("top-level output is not an object")
                correct = all(
                    key in parsed and equal(parsed[key], expected)
                    for key, expected in case["expected"].items()
                )
                return Result(
                    model=model,
                    case_id=case["id"],
                    repeat=repeat,
                    transport_ok=True,
                    json_ok=True,
                    correct=correct,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    output=output,
                )
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return Result(
                    model=model,
                    case_id=case["id"],
                    repeat=repeat,
                    transport_ok=True,
                    json_ok=False,
                    correct=False,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    error=f"bad structured response: {exc}",
                    output=response.text[:800],
                )
        last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        time.sleep(2.0)

    return Result(
        model=model,
        case_id=case["id"],
        repeat=repeat,
        transport_ok=False,
        json_ok=False,
        correct=False,
        latency_s=time.perf_counter() - started,
        attempts=2,
        error=last_error or "request failed",
    )


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")
    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(35.0, connect=10.0)) as client:
        for model in MODELS:
            for case in CASES:
                for repeat in range(REPEATS):
                    result = run_once(client, api_key, model, case, repeat)
                    results.append(result)
                    print(
                        f"{model} [{case['id']} #{repeat}] correct={result.correct} "
                        f"transport={result.transport_ok} json={result.json_ok} "
                        f"latency={result.latency_s:.2f}s attempts={result.attempts} "
                        f"error={result.error or '-'}"
                    )

    os.makedirs("artifacts/nim-consistency", exist_ok=True)
    with open("artifacts/nim-consistency/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"repeats": REPEATS, "results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )
    print("\n| Model | Case | Correct/available | Unavailable |")
    print("|---|---|---:|---:|")
    for model in MODELS:
        for case in CASES:
            items = [
                x for x in results if x.model == model and x.case_id == case["id"]
            ]
            available = [x for x in items if x.transport_ok]
            correct = sum(x.correct for x in available)
            unavailable = len(items) - len(available)
            print(
                f"| `{model}` | {case['id']} | {correct}/{len(available)} | "
                f"{unavailable} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Benchmark trigger: 2026-09-17T15:26Z
