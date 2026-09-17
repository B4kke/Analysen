from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import statistics
import struct
import threading
import time
import unicodedata
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://integrate.api.nvidia.com/v1"
FIXTURE_PATH = Path("tests/fixtures/nim_benchmark_no.json")
OUTPUT_DIR = Path("artifacts/nim-benchmark")

TEXT_MODELS = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]
VISION_MODELS = [
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]
EMBED_MODEL = "nvidia/nemotron-3-embed-1b"
TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class CallResult:
    ok: bool
    latency_s: float
    attempts: int
    status_code: int | None = None
    text: str = ""
    payload: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class CaseResult:
    model: str
    suite: str
    case_id: str
    ok: bool
    score: float
    max_score: float
    latency_s: float
    attempts: int
    json_valid: bool | None = None
    output: str = ""
    error: str | None = None
    usage: dict[str, Any] | None = None


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(value: Any) -> str:
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text)


def extract_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates = [stripped]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
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


def score_json_fields(output: str, expected: dict[str, Any]) -> tuple[float, bool]:
    parsed = extract_json(output)
    if parsed is None:
        return 0.0, False
    points = 0.0
    for key, expected_value in expected.items():
        if key not in parsed:
            continue
        actual = parsed[key]
        if isinstance(expected_value, bool):
            if actual is expected_value:
                points += 1.0
        elif normalize(actual) == normalize(expected_value):
            points += 1.0
    return points / max(1, len(expected)), True


def score_contains_all(output: str, expected: list[str]) -> float:
    haystack = output.casefold()
    return sum(1 for item in expected if item.casefold() in haystack) / max(1, len(expected))


def score_contains_groups(output: str, groups: list[list[str]]) -> float:
    haystack = output.casefold()
    matched = 0
    for group in groups:
        if any(item.casefold() in haystack for item in group):
            matched += 1
    return matched / max(1, len(groups))


def model_sampling(model: str) -> tuple[float, float]:
    if "nemotron-3-super" in model or "nemotron-3-ultra" in model:
        return 1.0, 0.95
    if "nemotron-3.5-lightning" in model:
        return 1.0, 0.95
    if "omni" in model:
        return 0.6, 0.95
    return 0.2, 0.95


def retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(8.0, max(0.5, float(header)))
        except ValueError:
            pass
    return min(8.0, 1.5 * (2**attempt))


def compact_error(response: httpx.Response) -> str:
    text = response.text.replace("\n", " ").strip()
    return f"HTTP {response.status_code}: {text[:400]}"


def post_json(
    *,
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    max_attempts: int,
    deadline: float,
) -> CallResult:
    started = time.perf_counter()
    last_error: str | None = None
    last_status: int | None = None
    for attempt in range(max_attempts):
        if time.monotonic() >= deadline:
            return CallResult(
                ok=False,
                latency_s=time.perf_counter() - started,
                attempts=attempt,
                error="global benchmark deadline reached",
            )
        try:
            response = client.post(url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < max_attempts:
                time.sleep(min(5.0, 1.5 * (2**attempt)))
                continue
            break

        last_status = response.status_code
        if response.is_success:
            try:
                body = response.json()
            except ValueError as exc:
                return CallResult(
                    ok=False,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    status_code=response.status_code,
                    error=f"invalid JSON response: {exc}",
                )
            return CallResult(
                ok=True,
                latency_s=time.perf_counter() - started,
                attempts=attempt + 1,
                status_code=response.status_code,
                payload=body,
                usage=body.get("usage") if isinstance(body, dict) else None,
            )

        last_error = compact_error(response)
        if response.status_code not in TRANSIENT_STATUSES or attempt + 1 >= max_attempts:
            break
        delay = retry_after_seconds(response, attempt)
        if time.monotonic() + delay >= deadline:
            break
        time.sleep(delay)

    return CallResult(
        ok=False,
        latency_s=time.perf_counter() - started,
        attempts=max_attempts,
        status_code=last_status,
        error=last_error or "unknown request failure",
    )


def chat_call(
    *,
    client: httpx.Client,
    headers: dict[str, str],
    model: str,
    messages: list[dict[str, Any]],
    reasoning: bool,
    max_attempts: int,
    deadline: float,
    max_tokens: int = 240,
) -> CallResult:
    temperature, top_p = model_sampling(model)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }
    if model.startswith("nvidia/nemotron-3") and "omni" not in model:
        payload["chat_template_kwargs"] = {"enable_thinking": reasoning}
        if reasoning:
            payload["reasoning_budget"] = 512
    elif "omni" in model and reasoning:
        payload["reasoning_budget"] = 512

    result = post_json(
        client=client,
        url=f"{BASE_URL}/chat/completions",
        headers=headers,
        payload=payload,
        max_attempts=max_attempts,
        deadline=deadline,
    )
    if not result.ok or not result.payload:
        return result
    try:
        message = result.payload["choices"][0]["message"]
        content = message.get("content") or ""
        reasoning_text = message.get("reasoning_content") or ""
        if not content and reasoning_text:
            content = reasoning_text
        result.text = content
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        result.ok = False
        result.error = f"unexpected chat response shape: {exc}"
    return result


def run_text_case(
    *,
    client: httpx.Client,
    headers: dict[str, str],
    model: str,
    case: dict[str, Any],
    max_attempts: int,
    deadline: float,
) -> CaseResult:
    weight = float(case["weight"])
    call = chat_call(
        client=client,
        headers=headers,
        model=model,
        messages=[
            {"role": "system", "content": case["system"]},
            {"role": "user", "content": case["prompt"]},
        ],
        reasoning=bool(case.get("reasoning", False)),
        max_attempts=max_attempts,
        deadline=deadline,
    )
    if not call.ok:
        return CaseResult(
            model=model,
            suite="text",
            case_id=case["id"],
            ok=False,
            score=0.0,
            max_score=weight,
            latency_s=call.latency_s,
            attempts=call.attempts,
            error=call.error,
            usage=call.usage,
        )

    json_valid: bool | None = None
    ratio = 0.0
    scorer = case["scorer"]
    if scorer == "json_fields":
        ratio, json_valid = score_json_fields(call.text, case["expected"])
    elif scorer == "contains_all":
        ratio = score_contains_all(call.text, case["expected"])
    elif scorer == "contains_groups":
        ratio = score_contains_groups(call.text, case["expected"])
    else:
        raise ValueError(f"Unknown scorer: {scorer}")

    return CaseResult(
        model=model,
        suite="text",
        case_id=case["id"],
        ok=True,
        score=round(weight * ratio, 4),
        max_score=weight,
        latency_s=call.latency_s,
        attempts=call.attempts,
        json_valid=json_valid,
        output=call.text,
        usage=call.usage,
    )


def png_bytes(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    if len(pixels) != width * height:
        raise ValueError("pixel count mismatch")
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixels[y * width + x])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


FONT_5X7 = {
    " ": ["00000"] * 7,
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
}


def generated_text_png(text: str) -> bytes:
    scale = 8
    glyph_w = 5
    glyph_h = 7
    spacing = 1
    margin = 14
    width = margin * 2 + len(text) * (glyph_w + spacing) * scale
    height = margin * 2 + glyph_h * scale
    pixels = [(255, 255, 255)] * (width * height)
    cursor = margin
    for char in text.upper():
        glyph = FONT_5X7.get(char, FONT_5X7[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit != "1":
                    continue
                for sy in range(scale):
                    for sx in range(scale):
                        x = cursor + gx * scale + sx
                        y = margin + gy * scale + sy
                        pixels[y * width + x] = (0, 0, 0)
        cursor += (glyph_w + spacing) * scale
    return png_bytes(width, height, pixels)


def generated_color_png() -> bytes:
    width, height = 180, 90
    pixels: list[tuple[int, int, int]] = []
    for _y in range(height):
        for x in range(width):
            pixels.append((220, 30, 30) if x < width // 2 else (30, 80, 220))
    return png_bytes(width, height, pixels)


def data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def run_vision_case(
    *,
    client: httpx.Client,
    headers: dict[str, str],
    model: str,
    case: dict[str, Any],
    max_attempts: int,
    deadline: float,
) -> CaseResult:
    weight = float(case["weight"])
    if case["kind"] == "generated_text_image":
        image = generated_text_png(case["text"])
    elif case["kind"] == "generated_color_image":
        image = generated_color_png()
    else:
        raise ValueError(f"Unknown vision kind: {case['kind']}")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": case["prompt"]},
                {"type": "image_url", "image_url": {"url": data_uri(image)}},
            ],
        }
    ]
    call = chat_call(
        client=client,
        headers=headers,
        model=model,
        messages=messages,
        reasoning=False,
        max_attempts=max_attempts,
        deadline=deadline,
        max_tokens=180,
    )
    if not call.ok:
        return CaseResult(
            model=model,
            suite="vision",
            case_id=case["id"],
            ok=False,
            score=0.0,
            max_score=weight,
            latency_s=call.latency_s,
            attempts=call.attempts,
            error=call.error,
            usage=call.usage,
        )

    if case["scorer"] == "contains_all":
        ratio = score_contains_all(call.text, case["expected"])
    else:
        ratio = score_contains_groups(call.text, case["expected"])
    return CaseResult(
        model=model,
        suite="vision",
        case_id=case["id"],
        ok=True,
        score=round(weight * ratio, 4),
        max_score=weight,
        latency_s=call.latency_s,
        attempts=call.attempts,
        output=call.text,
        usage=call.usage,
    )


def cosine(a: list[float], b: list[float]) -> float:
    numerator = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return numerator / (norm_a * norm_b)


def embedding_request(
    *,
    client: httpx.Client,
    headers: dict[str, str],
    texts: list[str],
    input_type: str,
    max_attempts: int,
    deadline: float,
) -> CallResult:
    variants = [
        {
            "model": EMBED_MODEL,
            "input": texts,
            "input_type": input_type,
            "encoding_format": "float",
            "truncate": "END",
        },
        {
            "model": EMBED_MODEL,
            "input": texts,
            "input_type": input_type,
            "encoding_format": "float",
        },
        {"model": EMBED_MODEL, "input": texts, "encoding_format": "float"},
    ]
    last: CallResult | None = None
    for payload in variants:
        last = post_json(
            client=client,
            url=f"{BASE_URL}/embeddings",
            headers=headers,
            payload=payload,
            max_attempts=max_attempts,
            deadline=deadline,
        )
        if last.ok:
            return last
        if last.status_code not in {400, 422}:
            return last
    return last or CallResult(
        ok=False, latency_s=0.0, attempts=0, error="embedding call not attempted"
    )


def run_embedding_case(
    *,
    client: httpx.Client,
    headers: dict[str, str],
    case: dict[str, Any],
    max_attempts: int,
    deadline: float,
) -> CaseResult:
    started = time.perf_counter()
    query_call = embedding_request(
        client=client,
        headers=headers,
        texts=[case["query"]],
        input_type="query",
        max_attempts=max_attempts,
        deadline=deadline,
    )
    if not query_call.ok or not query_call.payload:
        return CaseResult(
            model=EMBED_MODEL,
            suite="embedding",
            case_id=case["id"],
            ok=False,
            score=0.0,
            max_score=1.0,
            latency_s=time.perf_counter() - started,
            attempts=query_call.attempts,
            error=query_call.error,
        )
    passage_call = embedding_request(
        client=client,
        headers=headers,
        texts=case["documents"],
        input_type="passage",
        max_attempts=max_attempts,
        deadline=deadline,
    )
    if not passage_call.ok or not passage_call.payload:
        return CaseResult(
            model=EMBED_MODEL,
            suite="embedding",
            case_id=case["id"],
            ok=False,
            score=0.0,
            max_score=1.0,
            latency_s=time.perf_counter() - started,
            attempts=query_call.attempts + passage_call.attempts,
            error=passage_call.error,
        )
    try:
        qvec = query_call.payload["data"][0]["embedding"]
        dvecs = [item["embedding"] for item in passage_call.payload["data"]]
        similarities = [cosine(qvec, dvec) for dvec in dvecs]
        top_index = max(range(len(similarities)), key=similarities.__getitem__)
        score = 1.0 if top_index == int(case["expected_top_index"]) else 0.0
        output = json.dumps(
            {"similarities": [round(value, 6) for value in similarities], "top_index": top_index},
            ensure_ascii=False,
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return CaseResult(
            model=EMBED_MODEL,
            suite="embedding",
            case_id=case["id"],
            ok=False,
            score=0.0,
            max_score=1.0,
            latency_s=time.perf_counter() - started,
            attempts=query_call.attempts + passage_call.attempts,
            error=f"unexpected embedding response: {exc}",
        )
    return CaseResult(
        model=EMBED_MODEL,
        suite="embedding",
        case_id=case["id"],
        ok=True,
        score=score,
        max_score=1.0,
        latency_s=time.perf_counter() - started,
        attempts=query_call.attempts + passage_call.attempts,
        output=output,
    )


def run_text_model(
    *,
    model: str,
    cases: list[dict[str, Any]],
    headers: dict[str, str],
    request_timeout: float,
    max_attempts: int,
    deadline: float,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    timeout = httpx.Timeout(request_timeout, connect=min(10.0, request_timeout))
    with httpx.Client(timeout=timeout) as client:
        for case in cases:
            if time.monotonic() >= deadline:
                break
            results.append(
                run_text_case(
                    client=client,
                    headers=headers,
                    model=model,
                    case=case,
                    max_attempts=max_attempts,
                    deadline=deadline,
                )
            )
    return results


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    by_model: dict[str, list[CaseResult]] = {}
    for result in results:
        by_model.setdefault(result.model, []).append(result)

    models: list[dict[str, Any]] = []
    for model, items in by_model.items():
        total = sum(item.score for item in items)
        maximum = sum(item.max_score for item in items)
        latencies = [item.latency_s for item in items if item.latency_s > 0]
        successful_calls = sum(1 for item in items if item.ok)
        json_items = [item for item in items if item.json_valid is not None]
        models.append(
            {
                "model": model,
                "score_pct": round(100.0 * total / maximum, 2) if maximum else 0.0,
                "score": round(total, 4),
                "max_score": round(maximum, 4),
                "successful_cases": successful_calls,
                "cases": len(items),
                "success_rate_pct": round(100.0 * successful_calls / len(items), 2),
                "median_latency_s": round(statistics.median(latencies), 3) if latencies else None,
                "p95_latency_s": round(max(latencies), 3) if latencies else None,
                "json_valid_rate_pct": (
                    round(
                        100.0 * sum(1 for item in json_items if item.json_valid) / len(json_items),
                        2,
                    )
                    if json_items
                    else None
                ),
            }
        )
    models.sort(key=lambda item: (-item["score_pct"], item["median_latency_s"] or 10**9))
    return {"models": models}


def write_outputs(results: list[CaseResult], metadata: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    payload = {
        "metadata": metadata,
        "summary": summary,
        "results": [asdict(result) for result in results],
    }
    json_path = OUTPUT_DIR / "results.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# NVIDIA NIM benchmark",
        "",
        f"- Started: `{metadata['started_at_utc']}`",
        f"- Wall limit: `{metadata['wall_limit_s']}s`",
        f"- Per-request timeout: `{metadata['request_timeout_s']}s`",
        f"- Max attempts: `{metadata['max_attempts']}`",
        f"- Workers: `{metadata['workers']}`",
        f"- Deadline reached: `{metadata['deadline_reached']}`",
        "",
        "## Model summary",
        "",
        "| Model | Score | Success | Median latency | JSON valid |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in summary["models"]:
        json_rate = (
            "-"
            if item["json_valid_rate_pct"] is None
            else f"{item['json_valid_rate_pct']:.1f}%"
        )
        latency = "-" if item["median_latency_s"] is None else f"{item['median_latency_s']:.2f}s"
        lines.append(
            f"| `{item['model']}` | {item['score_pct']:.1f}% | "
            f"{item['successful_cases']}/{item['cases']} | {latency} | {json_rate} |"
        )
    lines.extend(["", "## Cases", ""])
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        lines.append(
            f"- **{status}** `{result.model}` / `{result.suite}` / `{result.case_id}`: "
            f"{result.score:.2f}/{result.max_score:.2f}, "
            f"{result.latency_s:.2f}s, attempts={result.attempts}"
        )
        if result.error:
            lines.append(f"  - Error: `{result.error[:500]}`")
    md_path = OUTPUT_DIR / "summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded benchmark for NVIDIA NIM models used by Analysen"
    )
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--request-timeout", type=float, default=45.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--wall-limit", type=float, default=720.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--skip-vision", action="store_true")
    parser.add_argument("--skip-embedding", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is missing")
    if args.max_attempts < 1 or args.max_attempts > 3:
        raise SystemExit("--max-attempts must be between 1 and 3")
    if args.request_timeout < 5 or args.request_timeout > 120:
        raise SystemExit("--request-timeout must be between 5 and 120 seconds")
    if args.wall_limit < 60 or args.wall_limit > 1200:
        raise SystemExit("--wall-limit must be between 60 and 1200 seconds")
    if args.workers < 1 or args.workers > 3:
        raise SystemExit("--workers must be between 1 and 3")

    fixture = load_fixture(args.fixture)
    started_wall = time.time()
    deadline = time.monotonic() + args.wall_limit
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    results: list[CaseResult] = []
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                run_text_model,
                model=model,
                cases=fixture["text_cases"],
                headers=headers,
                request_timeout=args.request_timeout,
                max_attempts=args.max_attempts,
                deadline=deadline,
            ): model
            for model in TEXT_MODELS
        }
        for future in as_completed(futures):
            model = futures[future]
            try:
                model_results = future.result()
            except Exception as exc:  # noqa: BLE001 - benchmark must survive one model failure
                model_results = [
                    CaseResult(
                        model=model,
                        suite="text",
                        case_id="model_runner",
                        ok=False,
                        score=0.0,
                        max_score=1.0,
                        latency_s=0.0,
                        attempts=0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ]
            with lock:
                results.extend(model_results)

    timeout = httpx.Timeout(args.request_timeout, connect=min(10.0, args.request_timeout))
    if not args.skip_vision and time.monotonic() < deadline:
        with httpx.Client(timeout=timeout) as client:
            for model in VISION_MODELS:
                for case in fixture["vision_cases"]:
                    if time.monotonic() >= deadline:
                        break
                    results.append(
                        run_vision_case(
                            client=client,
                            headers=headers,
                            model=model,
                            case=case,
                            max_attempts=args.max_attempts,
                            deadline=deadline,
                        )
                    )

    if not args.skip_embedding and time.monotonic() < deadline:
        with httpx.Client(timeout=timeout) as client:
            results.append(
                run_embedding_case(
                    client=client,
                    headers=headers,
                    case=fixture["embedding_case"],
                    max_attempts=args.max_attempts,
                    deadline=deadline,
                )
            )

    metadata = {
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_wall)),
        "finished_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - started_wall, 3),
        "wall_limit_s": args.wall_limit,
        "request_timeout_s": args.request_timeout,
        "max_attempts": args.max_attempts,
        "workers": args.workers,
        "deadline_reached": time.monotonic() >= deadline,
        "text_models": TEXT_MODELS,
        "vision_models": [] if args.skip_vision else VISION_MODELS,
        "embedding_model": None if args.skip_embedding else EMBED_MODEL,
    }
    json_path, md_path = write_outputs(results, metadata)
    print(md_path.read_text(encoding="utf-8"))
    print(f"JSON results: {json_path}")

    successful = sum(1 for result in results if result.ok)
    if successful == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
