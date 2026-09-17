from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

BASE_URL = "https://integrate.api.nvidia.com/v1"
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}

SYSTEM = (
    "Du arbeider med entity resolution. Ikke gjett når identifikatorene ikke passer. "
    "Svar KUN med gyldig JSON."
)
PROMPT = (
    "Mål: Kari Testperson, født 14.05.1987, Nannestad, kjent styreverv i Fjordlys Demo AS. "
    "Kandidat A: Kari Testperson, født 1979, Bergen, ingen kobling til Fjordlys. "
    "Kandidat B: Kari Testperson, født 14.05.1987, Nannestad, styremedlem i Fjordlys Demo AS. "
    "Kandidat C: Kari Testperson, født 14.05.1987, Tromsø, ingen virksomhetskobling. "
    "Returner nøyaktig JSON-form: "
    '{"match":"A|B|C|UNRESOLVED","confidence":"high|medium|low","reason":"kort begrunnelse"}.'
)


@dataclass
class Result:
    model: str
    variant: str
    ok: bool
    schema_ok: bool
    latency_s: float
    attempts: int
    status_code: int | None = None
    finish_reason: str | None = None
    error: str | None = None
    output: str = ""
    usage: dict[str, Any] | None = None


def request_once(
    client: httpx.Client,
    *,
    api_key: str,
    model: str,
    variant: str,
    temperature: float,
    top_p: float,
    max_tokens: int = 512,
) -> Result:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": PROMPT},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
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
                output = message.get("content") or ""
                parsed = json.loads(output)
                schema_ok = (
                    isinstance(parsed, dict)
                    and parsed.get("match") == "B"
                    and parsed.get("confidence") == "high"
                    and isinstance(parsed.get("reason"), str)
                    and bool(parsed.get("reason", "").strip())
                )
                return Result(
                    model=model,
                    variant=variant,
                    ok=True,
                    schema_ok=schema_ok,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    status_code=200,
                    finish_reason=choice.get("finish_reason"),
                    output=output,
                    usage=body.get("usage"),
                )
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return Result(
                    model=model,
                    variant=variant,
                    ok=True,
                    schema_ok=False,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    status_code=200,
                    error=f"invalid structured response: {exc}",
                    output=response.text[:1000],
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
        variant=variant,
        ok=False,
        schema_ok=False,
        latency_s=time.perf_counter() - started,
        attempts=2,
        status_code=last_status,
        error=last_error or "request failed",
    )


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")

    probes = [
        ("nvidia/nemotron-3.5-lightning-30b-a3b", "recommended", 1.0, 0.95),
        ("nvidia/nemotron-3.5-lightning-30b-a3b", "deterministic", 0.0, 1.0),
        ("nvidia/nemotron-3-super-120b-a12b", "recommended", 1.0, 0.95),
        ("nvidia/nemotron-3-ultra-550b-a55b", "recommended", 1.0, 0.95),
        ("google/gemma-4-31b-it", "deterministic", 0.2, 1.0),
    ]

    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(45.0)) as client:
        for model, variant, temperature, top_p in probes:
            result = request_once(
                client,
                api_key=api_key,
                model=model,
                variant=variant,
                temperature=temperature,
                top_p=top_p,
            )
            results.append(result)
            print(
                f"{model} [{variant}] ok={result.ok} schema_ok={result.schema_ok} "
                f"latency={result.latency_s:.2f}s attempts={result.attempts} "
                f"finish={result.finish_reason} error={result.error or '-'}"
            )
            if result.output:
                print(result.output[:800].replace("\n", " "))

    payload = {
        "probe": "production_json_identity_disambiguation",
        "results": [asdict(result) for result in results],
    }
    os.makedirs("artifacts/nim-structured-probe", exist_ok=True)
    with open("artifacts/nim-structured-probe/results.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print("\n| Model | Variant | Schema | Latency | Finish |")
    print("|---|---|---:|---:|---|")
    for result in results:
        print(
            f"| `{result.model}` | {result.variant} | "
            f"{'PASS' if result.schema_ok else 'FAIL'} | {result.latency_s:.2f}s | "
            f"{result.finish_reason or '-'} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
