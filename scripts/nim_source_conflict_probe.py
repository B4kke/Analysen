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

CASES: list[dict[str, Any]] = [
    {
        "id": "current_chair_authority_recency",
        "sources": [
            {
                "id": "D1",
                "type": "official_registry_snapshot",
                "published": "2025-11-01",
                "text": "Styreleder: Bjørn Sæther. Snapshot fra 2025.",
            },
            {
                "id": "D2",
                "type": "local_news",
                "published": "2026-08-20",
                "text": (
                    "Avisen omtaler Ola Kontroll som selskapets styreleder, "
                    "uten lenke til register."
                ),
            },
            {
                "id": "D3",
                "type": "official_registry",
                "published": "2026-09-16",
                "text": "Gjeldende roller: Styreleder Åse Ødegård. Registrert fra 2025-05-15.",
            },
        ],
        "question": "Hvem er dokumentert nåværende styreleder?",
        "expected": {
            "status": "VERIFIED_FACT",
            "value": "Åse Ødegård",
            "supporting_sources": ["D3"],
        },
    },
    {
        "id": "current_address_newer_registry",
        "sources": [
            {
                "id": "A1",
                "type": "annual_report",
                "published": "2026-04-30",
                "text": "Forretningsadresse: Havnegata 4, 6005 Ålesund.",
            },
            {
                "id": "A2",
                "type": "official_registry",
                "published": "2026-09-15",
                "text": (
                    "Forretningsadresse: Fjordvegen 18, 6003 Ålesund. "
                    "Sist oppdatert 2026-09-15."
                ),
            },
            {
                "id": "A3",
                "type": "directory_aggregator",
                "published": "2026-09-17",
                "text": "Adresse oppgitt som Havnegata 4. Datakilde og oppdateringsdato er ukjent.",
            },
        ],
        "question": "Hva er best dokumentert gjeldende forretningsadresse?",
        "expected": {
            "status": "VERIFIED_FACT",
            "value": "Fjordvegen 18, 6003 Ålesund",
            "supporting_sources": ["A2"],
        },
    },
    {
        "id": "equal_authority_unresolved",
        "sources": [
            {
                "id": "U1",
                "type": "official_filing",
                "published": "2026-09-10",
                "text": "Aksjonær Nordlys Holding AS eier 45 %.",
            },
            {
                "id": "U2",
                "type": "official_filing",
                "published": "2026-09-10",
                "text": "Aksjonær Nordlys Holding AS eier 55 %.",
            },
            {
                "id": "U3",
                "type": "blog",
                "published": "2026-09-12",
                "text": "Bloggen hevder at eierandelen er 70 %.",
            },
        ],
        "question": "Hva er dokumentert eierandel for Nordlys Holding AS?",
        "expected": {
            "status": "UNRESOLVED",
            "value": None,
            "supporting_sources": ["U1", "U2"],
        },
    },
    {
        "id": "rumour_vs_authoritative_status",
        "sources": [
            {
                "id": "S1",
                "type": "forum_post",
                "published": "2026-09-17",
                "text": "En anonym bruker skriver at selskapet skal være konkurs.",
            },
            {
                "id": "S2",
                "type": "official_registry",
                "published": "2026-09-17",
                "text": "Status: AKTIV. Ingen registrert konkursåpning. Oppdatert 2026-09-17.",
            },
            {
                "id": "S3",
                "type": "company_website",
                "published": "2026-09-16",
                "text": "Selskapet opplyser at ordinær drift fortsetter.",
            },
        ],
        "question": "Er konkurs påvist i kildene?",
        "expected": {
            "status": "CONTRADICTED",
            "value": False,
            "supporting_sources": ["S2"],
        },
    },
    {
        "id": "historical_true_not_current",
        "sources": [
            {
                "id": "H1",
                "type": "official_registry_snapshot",
                "published": "2024-03-01",
                "text": "Daglig leder: Kari Testperson.",
            },
            {
                "id": "H2",
                "type": "official_registry",
                "published": "2026-09-17",
                "text": "Daglig leder: Ola Kontroll. Kari Testperson fratrådte 2025-12-31.",
            },
            {
                "id": "H3",
                "type": "old_press_release",
                "published": "2024-04-01",
                "text": "Kari Testperson omtales som daglig leder.",
            },
        ],
        "question": "Er Kari Testperson dokumentert som nåværende daglig leder?",
        "expected": {
            "status": "CONTRADICTED",
            "value": False,
            "supporting_sources": ["H2"],
        },
    },
]


@dataclass
class Result:
    model: str
    case_id: str
    transport_ok: bool
    json_ok: bool
    status_ok: bool
    value_ok: bool
    sources_ok: bool
    all_correct: bool
    latency_s: float
    attempts: int
    error: str | None = None
    output: str = ""


def normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def source_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value}


def run_case(
    client: httpx.Client,
    api_key: str,
    model: str,
    case: dict[str, Any],
) -> Result:
    system = (
        "Du er en kildekritisk norsk analysemodell. Skill historiske fakta fra nåstatus. "
        "Prioriter autoritative primærkilder og relevant oppdateringsdato. Ikke slå sammen "
        "motstridende fakta. Hvis like autoritative og like ferske kilder motsier hverandre, "
        "bruk UNRESOLVED. Returner KUN JSON med status, value, supporting_sources og reason. "
        "status må være VERIFIED_FACT, UNRESOLVED eller CONTRADICTED. supporting_sources "
        "må kun inneholde kilde-ID-er som direkte støtter konklusjonen."
    )
    prompt = json.dumps(
        {"sources": case["sources"], "question": case["question"]},
        ensure_ascii=False,
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 1200,
        "stream": False,
    }
    if model == "nvidia/nemotron-3.5-lightning-30b-a3b":
        payload.update({"temperature": 1.0, "top_p": 0.95})
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    elif model.startswith("nvidia/nemotron-"):
        payload.update({"temperature": 0.6, "top_p": 0.95})
        payload["chat_template_kwargs"] = {"enable_thinking": True}
    else:
        payload.update({"temperature": 0.2, "top_p": 1.0})

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
                f"{BASE_URL}/chat/completions", headers=headers, json=payload
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
                expected = case["expected"]
                status_ok = parsed.get("status") == expected["status"]
                value_ok = normalize(parsed.get("value")) == normalize(expected["value"])
                sources_ok = source_set(parsed.get("supporting_sources")) == source_set(
                    expected["supporting_sources"]
                )
                return Result(
                    model=model,
                    case_id=case["id"],
                    transport_ok=True,
                    json_ok=True,
                    status_ok=status_ok,
                    value_ok=value_ok,
                    sources_ok=sources_ok,
                    all_correct=status_ok and value_ok and sources_ok,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    output=output,
                )
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return Result(
                    model=model,
                    case_id=case["id"],
                    transport_ok=True,
                    json_ok=False,
                    status_ok=False,
                    value_ok=False,
                    sources_ok=False,
                    all_correct=False,
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    error=f"bad structured response: {exc}",
                    output=response.text[:1200],
                )
        last_error = f"HTTP {response.status_code}: {response.text[:400]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        time.sleep(3.0)

    return Result(
        model=model,
        case_id=case["id"],
        transport_ok=False,
        json_ok=False,
        status_ok=False,
        value_ok=False,
        sources_ok=False,
        all_correct=False,
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
            for case in CASES:
                result = run_case(client, api_key, model, case)
                results.append(result)
                print(
                    f"{model} [{case['id']}] all={result.all_correct} "
                    f"status={result.status_ok} value={result.value_ok} "
                    f"sources={result.sources_ok} "
                    f"json={result.json_ok} latency={result.latency_s:.2f}s "
                    f"attempts={result.attempts} error={result.error or '-'}"
                )
                if result.output:
                    print(result.output[:1000].replace("\n", " "))

    os.makedirs("artifacts/nim-source-conflict", exist_ok=True)
    with open("artifacts/nim-source-conflict/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print("\n| Model | Fully correct available cases | Unavailable |")
    print("|---|---:|---:|")
    for model in MODELS:
        items = [item for item in results if item.model == model]
        available = [item for item in items if item.transport_ok]
        correct = sum(item.all_correct for item in available)
        print(f"| `{model}` | {correct}/{len(available)} | {len(items) - len(available)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Benchmark trigger: 2026-09-17T15:16Z
