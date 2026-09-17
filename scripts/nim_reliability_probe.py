from __future__ import annotations

import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
SEQUENTIAL_CALLS = 5
BURST_CALLS = 3


@dataclass
class Call:
    model: str
    phase: str
    index: int
    initial_ok: bool
    recovered: bool
    final_ok: bool
    initial_status: int | None
    final_status: int | None
    attempts: int
    latency_s: float
    json_correct: bool
    error: str | None = None


def sampling(model: str) -> tuple[float, float]:
    if model.startswith("nvidia/nemotron-"):
        return 1.0, 0.95
    return 0.2, 1.0


def payload_for(model: str, phase: str, index: int) -> dict[str, Any]:
    temperature, top_p = sampling(model)
    marker = f"NÅL-{phase.upper()}-{index:02d}-ØRN"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Svar KUN med gyldig JSON. Ikke forklar.",
            },
            {
                "role": "user",
                "content": (
                    "Returner marker nøyaktig som gitt og sum av 37 + 58. "
                    f"Marker: {marker}. JSON-felt: marker, sum."
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 160,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }
    if model.startswith("nvidia/nemotron-"):
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return payload


def validate(text: str, phase: str, index: int) -> bool:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    expected_marker = f"NÅL-{phase.upper()}-{index:02d}-ØRN"
    return parsed.get("marker") == expected_marker and parsed.get("sum") == 95


def execute_call(
    api_key: str,
    model: str,
    phase: str,
    index: int,
) -> Call:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = payload_for(model, phase, index)
    started = time.perf_counter()
    initial_status: int | None = None
    final_status: int | None = None
    last_error = ""
    initial_ok = False

    with httpx.Client(timeout=httpx.Timeout(35.0, connect=10.0)) as client:
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
                return Call(
                    model=model,
                    phase=phase,
                    index=index,
                    initial_ok=False,
                    recovered=False,
                    final_ok=False,
                    initial_status=initial_status,
                    final_status=final_status,
                    attempts=attempt + 1,
                    latency_s=time.perf_counter() - started,
                    json_correct=False,
                    error=last_error,
                )

            if attempt == 0:
                initial_status = response.status_code
            final_status = response.status_code
            if response.status_code == 200:
                if attempt == 0:
                    initial_ok = True
                try:
                    body = response.json()
                    content = body["choices"][0]["message"].get("content") or ""
                    correct = validate(content.strip(), phase, index)
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    correct = False
                    last_error = f"bad response shape: {exc}"
                return Call(
                    model=model,
                    phase=phase,
                    index=index,
                    initial_ok=initial_ok,
                    recovered=attempt > 0,
                    final_ok=True,
                    initial_status=initial_status,
                    final_status=final_status,
                    attempts=attempt + 1,
                    latency_s=time.perf_counter() - started,
                    json_correct=correct,
                    error=None if correct else last_error or "incorrect JSON payload",
                )

            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code not in TRANSIENT or attempt == 1:
                break
            time.sleep(2.0)

    return Call(
        model=model,
        phase=phase,
        index=index,
        initial_ok=False,
        recovered=False,
        final_ok=False,
        initial_status=initial_status,
        final_status=final_status,
        attempts=2,
        latency_s=time.perf_counter() - started,
        json_correct=False,
        error=last_error or "request failed",
    )


def percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return ordered[rank]


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")

    calls: list[Call] = []
    for model in MODELS:
        for index in range(SEQUENTIAL_CALLS):
            result = execute_call(api_key, model, "sequential", index)
            calls.append(result)
            print(
                f"SEQ {model} #{index}: initial={result.initial_ok} "
                f"final={result.final_ok} recovered={result.recovered} "
                f"status={result.initial_status}->{result.final_status} "
                f"correct={result.json_correct} latency={result.latency_s:.2f}s"
            )

        with ThreadPoolExecutor(max_workers=BURST_CALLS) as executor:
            futures = [
                executor.submit(execute_call, api_key, model, "burst", index)
                for index in range(BURST_CALLS)
            ]
            for future in as_completed(futures):
                result = future.result()
                calls.append(result)
                print(
                    f"BURST {model} #{result.index}: initial={result.initial_ok} "
                    f"final={result.final_ok} recovered={result.recovered} "
                    f"status={result.initial_status}->{result.final_status} "
                    f"correct={result.json_correct} latency={result.latency_s:.2f}s"
                )
        time.sleep(1.0)

    summaries: list[dict[str, Any]] = []
    for model in MODELS:
        items = [item for item in calls if item.model == model]
        latencies = [item.latency_s for item in items if item.final_ok]
        status_counts: dict[str, int] = {}
        for item in items:
            key = str(item.initial_status or "transport")
            status_counts[key] = status_counts.get(key, 0) + 1
        summaries.append(
            {
                "model": model,
                "calls": len(items),
                "initial_success_rate": sum(x.initial_ok for x in items) / len(items),
                "final_success_rate": sum(x.final_ok for x in items) / len(items),
                "correct_rate": sum(x.json_correct for x in items) / len(items),
                "recovered_calls": sum(x.recovered for x in items),
                "median_latency_s": statistics.median(latencies) if latencies else None,
                "p95_latency_s": percentile_95(latencies),
                "initial_status_counts": status_counts,
            }
        )

    os.makedirs("artifacts/nim-reliability", exist_ok=True)
    with open("artifacts/nim-reliability/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {
                "sequential_calls_per_model": SEQUENTIAL_CALLS,
                "burst_calls_per_model": BURST_CALLS,
                "summary": summaries,
                "calls": [asdict(item) for item in calls],
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print("\n| Model | Initial | Final | Correct | Recovered | Median | P95 |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for item in summaries:
        median = item["median_latency_s"]
        p95 = item["p95_latency_s"]
        print(
            f"| `{item['model']}` | {item['initial_success_rate']:.0%} | "
            f"{item['final_success_rate']:.0%} | {item['correct_rate']:.0%} | "
            f"{item['recovered_calls']} | "
            f"{median:.2f}s | {p95:.2f}s |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
