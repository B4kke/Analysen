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
        "id": "prokura_vs_signature",
        "prompt": (
            "Registerutdrag: 'Signatur: Styrets leder alene. Prokura: Daglig leder alene.' "
            "Returner KUN JSON med who_can_sign_for_company og who_has_prokura. Ikke slå "
            "begrepene sammen."
        ),
        "expected": {
            "who_can_sign_for_company": "Styrets leder alene",
            "who_has_prokura": "Daglig leder alene",
        },
    },
    {
        "id": "liquidation_not_bankruptcy",
        "prompt": (
            "Statusfelt: 'Selskapet er under frivillig avvikling. Konkurs: Nei.' "
            "Returner KUN JSON med in_liquidation og bankrupt."
        ),
        "expected": {"in_liquidation": True, "bankrupt": False},
    },
    {
        "id": "forced_dissolution_not_same_as_bankruptcy",
        "prompt": (
            "Registermerknad: 'Tvangsoppløsning besluttet. Det foreligger ingen registrert "
            "konkursåpning.' Returner KUN JSON med forced_dissolution og bankruptcy_opened."
        ),
        "expected": {"forced_dissolution": True, "bankruptcy_opened": False},
    },
    {
        "id": "beneficial_owner_indirect",
        "prompt": (
            "Eierkjede: Åse Ødegård eier 80 % av Holding AS. Holding AS eier 40 % av Drift AS. "
            "Åse eier i tillegg 5 % direkte i Drift AS. Returner KUN JSON med indirect_pct, "
            "direct_pct og effective_pct for Åse i Drift AS."
        ),
        "expected": {"indirect_pct": 32.0, "direct_pct": 5.0, "effective_pct": 37.0},
    },
    {
        "id": "unit_vs_business_register",
        "prompt": (
            "Tekst: 'Enheten er registrert i Enhetsregisteret, men ikke i Foretaksregisteret.' "
            "Returner KUN JSON med registered_unit_register og registered_business_register."
        ),
        "expected": {
            "registered_unit_register": True,
            "registered_business_register": False,
        },
    },
    {
        "id": "deleted_entity_historical_fact",
        "prompt": (
            "Registerhistorikk: 'Foretaket ble slettet 12.02.2025. Tidligere daglig leder var "
            "Kari Testperson.' Returner KUN JSON med currently_active og former_manager."
        ),
        "expected": {"currently_active": False, "former_manager": "Kari Testperson"},
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


def equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and abs(float(actual) - float(expected)) < 0.01
    return str(actual).strip().casefold() == str(expected).strip().casefold()


def run_case(client: httpx.Client, api_key: str, model: str, case: dict[str, Any]) -> Result:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Les norske selskaps- og registeropplysninger presist. Ikke anta at "
                    "beslektede juridiske/registermessige begreper betyr det samme. Svar kun JSON."
                ),
            },
            {"role": "user", "content": case["prompt"]},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 420,
        "stream": False,
    }
    if model.startswith("nvidia/nemotron-"):
        payload.update({"temperature": 1.0, "top_p": 0.95})
        payload["chat_template_kwargs"] = {"enable_thinking": False}
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
            response = client.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload)
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
                expected = case["expected"]
                hits = sum(
                    key in parsed and equal(parsed[key], value)
                    for key, value in expected.items()
                )
                return Result(
                    model=model,
                    case_id=case["id"],
                    transport_ok=True,
                    json_ok=True,
                    exact_fields=hits,
                    total_fields=len(expected),
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
        last_error = f"HTTP {response.status_code}: {response.text[:350]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        time.sleep(2.0)

    return Result(
        model=model,
        case_id=case["id"],
        transport_ok=False,
        json_ok=False,
        exact_fields=0,
        total_fields=len(case["expected"]),
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
                    f"{model} [{case['id']}] {result.exact_fields}/{result.total_fields} "
                    f"json={result.json_ok} latency={result.latency_s:.2f}s "
                    f"attempts={result.attempts} error={result.error or '-'}"
                )
                if result.output and result.exact_fields != result.total_fields:
                    print(result.output[:700].replace("\n", " "))

    os.makedirs("artifacts/nim-business-terms", exist_ok=True)
    with open("artifacts/nim-business-terms/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
