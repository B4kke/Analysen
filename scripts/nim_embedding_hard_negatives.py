from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-embed-1b"
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504, 529}

DOCUMENTS = [
    (
        "Per 17.09.2026 er Åse Ødegård sittende og aktiv styreleder i "
        "Skjærgårdsforvaltning Øst AS. Hun tiltrådte 15.05.2025."
    ),
    (
        "Bjørn Sæther var styreleder i Skjærgårdsforvaltning Øst AS fram til "
        "14.05.2025. Han er tidligere styreleder og er ikke lenger aktiv i vervet."
    ),
    (
        "Kari Testperson er påtroppende styreleder i Skjærgårdsforvaltning Øst AS "
        "fra 01.10.2026, men er ikke sittende styreleder per 17.09.2026."
    ),
    (
        "Det finnes ingen dokumentasjon som viser at Anne Eksempel er eller har vært "
        "styreleder i Skjærgårdsforvaltning Øst AS. Koblingen er ubekreftet."
    ),
    (
        "Øyvind Kjær er registrert som daglig leder i Skjærgårdsforvaltning Øst AS. "
        "Dette er et annet verv enn styreleder."
    ),
    (
        "Åse Ødegård var tidligere varamedlem før hun senere ble styreleder. Denne teksten "
        "omtaler den historiske varamedlemsrollen."
    ),
]

CASES = [
    {
        "id": "current_chair",
        "query": "Hvilket dokument viser hvem som er nåværende styreleder per 17.09.2026?",
        "expected": 0,
    },
    {
        "id": "former_chair",
        "query": "Finn dokumentet om den tidligere styrelederen som fratrådte i mai 2025.",
        "expected": 1,
    },
    {
        "id": "incoming_not_current",
        "query": (
            "Finn dokumentet om personen som er påtroppende, "
            "men ennå ikke sittende styreleder."
        ),
        "expected": 2,
    },
    {
        "id": "unverified_role",
        "query": "Finn teksten som sier at Anne Eksempels styrelederrolle ikke er dokumentert.",
        "expected": 3,
    },
    {
        "id": "manager_not_chair",
        "query": "Hvem er daglig leder, ikke styreleder? Finn riktig dokument.",
        "expected": 4,
    },
    {
        "id": "historical_deputy",
        "query": "Finn dokumentet om Åse Ødegårds tidligere rolle som varamedlem.",
        "expected": 5,
    },
]


@dataclass
class Result:
    case_id: str
    expected_index: int
    top_index: int | None
    rank_of_expected: int | None
    correct_top1: bool
    top1_margin: float | None
    latency_s: float
    attempts: int
    error: str | None = None


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def embed(
    client: httpx.Client,
    api_key: str,
    inputs: list[str],
    input_type: str,
) -> tuple[list[list[float]] | None, int, str | None]:
    payload: dict[str, Any] = {
        "model": MODEL,
        "input": inputs,
        "input_type": input_type,
        "encoding_format": "float",
        "truncate": "END",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    last_error = ""
    for attempt in range(2):
        try:
            response = client.post(
                f"{BASE_URL}/embeddings",
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                time.sleep(1.0)
                continue
            return None, attempt + 1, last_error
        if response.status_code == 200:
            try:
                body = response.json()
                return [item["embedding"] for item in body["data"]], attempt + 1, None
            except (KeyError, TypeError, ValueError) as exc:
                return None, attempt + 1, f"bad embedding response: {exc}"
        last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            return None, attempt + 1, last_error
        time.sleep(2.0)
    return None, 2, last_error or "request failed"


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")
    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(35.0, connect=10.0)) as client:
        docs, attempts, error = embed(client, api_key, DOCUMENTS, "passage")
        if docs is None:
            raise SystemExit(error or "document embedding failed")
        print(f"document batch embedded, attempts={attempts}")
        for case in CASES:
            started = time.perf_counter()
            query_vectors, query_attempts, query_error = embed(
                client,
                api_key,
                [case["query"]],
                "query",
            )
            latency = time.perf_counter() - started
            if query_vectors is None:
                results.append(
                    Result(
                        case_id=case["id"],
                        expected_index=case["expected"],
                        top_index=None,
                        rank_of_expected=None,
                        correct_top1=False,
                        top1_margin=None,
                        latency_s=latency,
                        attempts=query_attempts,
                        error=query_error,
                    )
                )
                continue
            similarities = [cosine(query_vectors[0], vector) for vector in docs]
            ranked = sorted(
                range(len(similarities)),
                key=similarities.__getitem__,
                reverse=True,
            )
            expected = case["expected"]
            margin = similarities[ranked[0]] - similarities[ranked[1]]
            result = Result(
                case_id=case["id"],
                expected_index=expected,
                top_index=ranked[0],
                rank_of_expected=ranked.index(expected) + 1,
                correct_top1=ranked[0] == expected,
                top1_margin=round(margin, 6),
                latency_s=latency,
                attempts=query_attempts,
            )
            results.append(result)
            print(
                f"{case['id']}: top={ranked[0]} expected={expected} "
                f"rank={result.rank_of_expected} margin={result.top1_margin} "
                f"latency={latency:.2f}s"
            )

    os.makedirs("artifacts/nim-embedding-hard-negatives", exist_ok=True)
    with open(
        "artifacts/nim-embedding-hard-negatives/results.json",
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {
                "model": MODEL,
                "documents": DOCUMENTS,
                "results": [asdict(item) for item in results],
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    passed = sum(item.correct_top1 for item in results)
    print(f"Top-1 hard negatives: {passed}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
