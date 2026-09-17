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

HARD_WORDS = [
    "tvangsfullbyrdelsesloven",
    "menneskerettighetskonvensjonsbrudd",
    "arbeidsgiveravgiftsgrunnlag",
    "skadeforsikringsselskapene",
    "eiendomsskattelovgivningen",
    "yrkesskadeforsikringsordningen",
    "høyesterettsjustitiarius",
    "skjærgårdsforvaltningsplanen",
]

CASES: list[dict[str, Any]] = [
    {
        "id": "compound_words_exact_array",
        "prompt": (
            "Returner JSON med feltet words som en JSON-array med nøyaktig åtte strenger. "
            "Kopier hvert ord tegn for tegn og behold rekkefølgen: "
            + ", ".join(HARD_WORDS)
        ),
        "expected": {"words": HARD_WORDS},
    },
    {
        "id": "incoming_vs_current_chair",
        "prompt": (
            "Tekst: 'Bjørn Sæther er sittende styreleder. Åse Ødegård er påtroppende "
            "styreleder og overtar 1. oktober.' Hvem er styreleder akkurat nå? Returner JSON "
            "med current_chair og incoming_chair."
        ),
        "expected": {
            "current_chair": "Bjørn Sæther",
            "incoming_chair": "Åse Ødegård",
        },
    },
    {
        "id": "cannot_be_ruled_out",
        "prompt": (
            "Tekst: 'Det kan ikke utelukkes at selskapet har uoppgjorte krav, men ingen "
            "dokumentasjon bekrefter dette.' Kan uoppgjorte krav rapporteres som bekreftet "
            "faktum? Returner JSON med confirmed som boolean og classification som "
            "VERIFIED eller UNVERIFIED."
        ),
        "expected": {"confirmed": False, "classification": "UNVERIFIED"},
    },
    {
        "id": "no_indication_wording",
        "prompt": (
            "Tekst: 'Det foreligger ingen holdepunkter for at Kari hadde disposisjonsrett "
            "over kontoen.' Returner JSON med evidence_for_access som boolean."
        ),
        "expected": {"evidence_for_access": False},
    },
    {
        "id": "nynorsk_licence_negation",
        "prompt": (
            "Nynorsk tekst: 'Verksemda har ikkje lenger løyve til å drive, og vedtaket vart "
            "endeleg 3. september 2026.' Returner JSON med language, licence_active og "
            "decision_date i YYYY-MM-DD."
        ),
        "expected": {
            "language": "nynorsk",
            "licence_active": False,
            "decision_date": "2026-09-03",
        },
    },
    {
        "id": "passive_voice_actor",
        "prompt": (
            "Tekst: 'Vedtaket fra kommunen ble omgjort av Statsforvalteren etter klage.' "
            "Returner JSON med original_decision_maker og reversing_authority."
        ),
        "expected": {
            "original_decision_maker": "kommunen",
            "reversing_authority": "Statsforvalteren",
        },
    },
    {
        "id": "effective_from_date",
        "prompt": (
            "Tekst: 'Ola Kontroll fratrådte vervet med virkning fra og med 31. desember "
            "2025. Endringen ble registrert 2. januar 2026.' Returner JSON med role_end_date "
            "og registration_date som YYYY-MM-DD."
        ),
        "expected": {
            "role_end_date": "2025-12-31",
            "registration_date": "2026-01-02",
        },
    },
    {
        "id": "norwegian_decimal_and_percent",
        "prompt": (
            "Tekst: 'Omsetningen økte fra 1 250 000,00 kr til 1 537 500,00 kr.' Returner "
            "JSON med old_revenue, new_revenue og increase_pct. increase_pct skal være "
            "prosentøkningen som tall, ikke brøk."
        ),
        "expected": {
            "old_revenue": 1250000.0,
            "new_revenue": 1537500.0,
            "increase_pct": 23.0,
        },
    },
    {
        "id": "address_unicode",
        "prompt": (
            "Tekst: 'Forretningsadresse: Ærfuglveien 12, 8392 Sørvågen. Avdeling: Å i "
            "Lofoten.' Returner JSON med street, postal_code, postal_place og branch_place."
        ),
        "expected": {
            "street": "Ærfuglveien 12",
            "postal_code": "8392",
            "postal_place": "Sørvågen",
            "branch_place": "Å i Lofoten",
        },
    },
    {
        "id": "double_negative_scope",
        "prompt": (
            "Tekst: 'Det er ikke riktig at selskapet aldri har hatt ansatte.' Returner JSON "
            "med has_had_employees som true, false eller null."
        ),
        "expected": {"has_had_employees": True},
    },
]


@dataclass
class Result:
    model: str
    case_id: str
    transport_ok: bool
    json_ok: bool
    exact_fields: int
    total_fields: int
    latency_s: float
    attempts: int
    error: str | None = None
    output: str = ""


def sampling(model: str) -> tuple[float, float]:
    if model.startswith("nvidia/nemotron-"):
        return 1.0, 0.95
    return 0.2, 1.0


def compare(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and abs(float(actual) - float(expected)) < 0.011
        )
    if isinstance(expected, list):
        return actual == expected
    return str(actual).strip().casefold() == str(expected).strip().casefold()


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
                    "Les norsk presist. Ikke gjett. Følg negasjoner og tidsuttrykk "
                    "bokstavelig. Svar KUN med gyldig JSON uten markdown."
                ),
            },
            {"role": "user", "content": case["prompt"]},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 500,
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
                output = (body["choices"][0]["message"].get("content") or "").strip()
                parsed = json.loads(output)
                if not isinstance(parsed, dict):
                    raise TypeError("top-level JSON is not an object")
                hits = sum(
                    1
                    for key, value in case["expected"].items()
                    if key in parsed and compare(parsed[key], value)
                )
                return Result(
                    model=model,
                    case_id=case["id"],
                    transport_ok=True,
                    json_ok=True,
                    exact_fields=hits,
                    total_fields=len(case["expected"]),
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
                    exact_fields=0,
                    total_fields=len(case["expected"]),
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    error=f"bad structured response: {exc}",
                    output=response.text[:1000],
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
        exact_fields=0,
        total_fields=len(case["expected"]),
        latency_s=time.perf_counter() - started,
        attempts=2,
        error=last_error or f"request failed with status {last_status}",
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
                    f"{model} [{case['id']}] fields="
                    f"{result.exact_fields}/{result.total_fields} "
                    f"json={result.json_ok} latency={result.latency_s:.2f}s "
                    f"attempts={result.attempts} error={result.error or '-'}"
                )

    os.makedirs("artifacts/nim-norwegian-language", exist_ok=True)
    with open(
        "artifacts/nim-norwegian-language/results.json",
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {"results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print("\n| Model | Exact fields | Total | Transport failures |")
    print("|---|---:|---:|---:|")
    for model in MODELS:
        items = [item for item in results if item.model == model]
        exact = sum(item.exact_fields for item in items)
        total = sum(item.total_fields for item in items)
        failures = sum(not item.transport_ok for item in items)
        print(f"| `{model}` | {exact} | {total} | {failures} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
