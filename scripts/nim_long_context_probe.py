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
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}
PARAGRAPHS = 260
POSITIONS = {
    "early": 8,
    "middle": PARAGRAPHS // 2,
    "late": PARAGRAPHS - 9,
}


@dataclass
class Result:
    model: str
    position: str
    transport_ok: bool
    json_ok: bool
    exact: bool
    latency_s: float
    attempts: int
    error: str | None = None
    output: str = ""


def build_context(position: int) -> str:
    paragraphs: list[str] = []
    for index in range(PARAGRAPHS):
        text = (
            f"Notat {index:03d}: Fiktiv kontrolltekst om arkivering, saksflyt, "
            "dokumentnummer, virksomhetsopplysninger og kildevurdering. "
            "Dette avsnittet inneholder ingen gjeldende kontrollkode. "
            f"Referansenummer R-{index:03d}-Ø er kun en avsnittsreferanse."
        )
        paragraphs.append(text)

    paragraphs[25] += " Historisk kontrollkode UTGÅTT-ØRN-1111 skal ignoreres."
    paragraphs[190] += " Testkode GAMMEL-NÅL-2222 er eksplisitt ugyldig."
    paragraphs[position] = (
        f"Notat {position:03d}: GJELDENDE KONTROLLPOST. Den eneste gyldige "
        "kontrollkoden er SKJÆR-ÅS-7421. Saksansvarlig kode er ØRN-53. "
        "Alle andre koder i materialet er historiske, ugyldige eller referanser."
    )
    return "\n\n".join(paragraphs)


def sampling(model: str) -> tuple[float, float]:
    if model.startswith("nvidia/nemotron-"):
        return 1.0, 0.95
    return 0.2, 1.0


def run_case(
    client: httpx.Client,
    api_key: str,
    model: str,
    label: str,
    position: int,
) -> Result:
    temperature, top_p = sampling(model)
    prompt = (
        "Les hele materialet. Finn KUN den koden som eksplisitt er merket som den eneste "
        "gyldige kontrollkoden. Ikke bruk historiske koder, testkoder eller "
        "avsnittsreferanser. Returner kun JSON med code og responsible_code.\n\n"
        + build_context(position)
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Svar KUN med gyldig JSON. Bevar Æ, Ø og Å nøyaktig.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 220,
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
                output = (body["choices"][0]["message"].get("content") or "").strip()
                parsed = json.loads(output)
                json_ok = isinstance(parsed, dict)
                exact = (
                    json_ok
                    and parsed.get("code") == "SKJÆR-ÅS-7421"
                    and parsed.get("responsible_code") == "ØRN-53"
                )
                return Result(
                    model=model,
                    position=label,
                    transport_ok=True,
                    json_ok=json_ok,
                    exact=exact,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    output=output,
                )
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return Result(
                    model=model,
                    position=label,
                    transport_ok=True,
                    json_ok=False,
                    exact=False,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    error=f"bad structured output: {exc}",
                    output=response.text[:1000],
                )

        last_error = f"HTTP {response.status_code}: {response.text[:400]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        time.sleep(3.0)

    return Result(
        model=model,
        position=label,
        transport_ok=False,
        json_ok=False,
        exact=False,
        latency_s=time.perf_counter() - started,
        attempts=2,
        error=last_error or "request failed",
    )


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")

    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(55.0, connect=10.0)) as client:
        for model in MODELS:
            for label, position in POSITIONS.items():
                result = run_case(client, api_key, model, label, position)
                results.append(result)
                print(
                    f"{model} [{label}] exact={result.exact} json={result.json_ok} "
                    f"latency={result.latency_s:.2f}s attempts={result.attempts} "
                    f"error={result.error or '-'}"
                )

    os.makedirs("artifacts/nim-long-context", exist_ok=True)
    with open("artifacts/nim-long-context/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {
                "paragraphs": PARAGRAPHS,
                "positions": POSITIONS,
                "results": [asdict(item) for item in results],
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
