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
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}

DOCUMENTS = [
    "Nordlys Eksempel AS har Kari Testperson registrert som daglig leder.",
    "Fjordlys Demo AS har Ola Kontroll registrert som styremedlem.",
    "Forretningsadressen til Vestvind Prøve AS er Havnegata 7 i Ålesund.",
    "Organisasjonsnummeret til Skogheim Test AS er 923 456 789.",
    "Selskapet har ingen registrert prokura, men styreleder har signatur alene.",
    "Årsregnskapet viser langsiktig gjeld på 4,2 millioner kroner.",
    "Verksemda har Kari Testperson som dagleg leiar ifølgje registerutdraget.",
    "Ingen av kildene dokumenterer at Anne Eksempel har en rolle i selskapet.",
    "Arbeidsmiljølovgivningen omtales i et generelt juridisk notat.",
    "Skjærgårdsforvaltningsplanen gjelder naturforvaltning og ikke selskapsroller.",
]

CASES = [
    {
        "id": "bokmal_role",
        "query": "Hvem er daglig leder i Nordlys Eksempel AS?",
        "expected": 0,
    },
    {
        "id": "nynorsk_role",
        "query": "Kven er dagleg leiar i verksemda?",
        "expected": 6,
    },
    {
        "id": "organization_number",
        "query": "Kva er organisasjonsnummeret til Skogheim Test AS?",
        "expected": 3,
    },
    {
        "id": "address_synonym",
        "query": "Hvor holder Vestvind Prøve AS til?",
        "expected": 2,
    },
    {
        "id": "legal_term_prokura",
        "query": "Finn dokumentet om signaturrett og prokura.",
        "expected": 4,
    },
    {
        "id": "financial_synonym",
        "query": "Hvilket dokument omtaler selskapets langsiktige låneforpliktelser?",
        "expected": 5,
    },
    {
        "id": "uncertainty_negative",
        "query": "Finn teksten som sier at Anne Eksempels selskapsrolle ikke er dokumentert.",
        "expected": 7,
    },
    {
        "id": "difficult_compound",
        "query": "Hvilket dokument handler om arbeidsmiljølovgivning?",
        "expected": 8,
    },
]


@dataclass
class Result:
    case_id: str
    expected_index: int
    top_index: int | None
    correct: bool
    margin: float | None
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


def post_embeddings(
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
                time.sleep(1.5)
                continue
            return None, attempt + 1, last_error

        if response.status_code == 200:
            try:
                body = response.json()
                vectors = [item["embedding"] for item in body["data"]]
                return vectors, attempt + 1, None
            except (KeyError, TypeError, ValueError) as exc:
                return None, attempt + 1, f"unexpected response: {exc}"

        last_error = f"HTTP {response.status_code}: {response.text[:500]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            return None, attempt + 1, last_error
        time.sleep(3.0)
    return None, 2, last_error or "request failed"


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")

    timeout = httpx.Timeout(45.0, connect=10.0)
    results: list[Result] = []
    with httpx.Client(timeout=timeout) as client:
        started = time.perf_counter()
        doc_vectors, doc_attempts, doc_error = post_embeddings(
            client,
            api_key,
            DOCUMENTS,
            "passage",
        )
        if doc_vectors is None:
            raise SystemExit(doc_error or "document embedding failed")
        doc_latency = time.perf_counter() - started
        print(
            f"documents embedded: count={len(doc_vectors)} "
            f"latency={doc_latency:.2f}s attempts={doc_attempts}"
        )

        for case in CASES:
            started = time.perf_counter()
            vectors, attempts, error = post_embeddings(
                client,
                api_key,
                [case["query"]],
                "query",
            )
            latency = time.perf_counter() - started
            if vectors is None:
                results.append(
                    Result(
                        case_id=case["id"],
                        expected_index=case["expected"],
                        top_index=None,
                        correct=False,
                        margin=None,
                        latency_s=latency,
                        attempts=attempts,
                        error=error,
                    )
                )
                continue

            similarities = [cosine(vectors[0], vector) for vector in doc_vectors]
            ranked = sorted(
                range(len(similarities)),
                key=similarities.__getitem__,
                reverse=True,
            )
            top_index = ranked[0]
            margin = similarities[ranked[0]] - similarities[ranked[1]]
            result = Result(
                case_id=case["id"],
                expected_index=case["expected"],
                top_index=top_index,
                correct=top_index == case["expected"],
                margin=round(margin, 6),
                latency_s=latency,
                attempts=attempts,
            )
            results.append(result)
            print(
                f"{case['id']}: expected={case['expected']} top={top_index} "
                f"correct={result.correct} margin={result.margin} "
                f"latency={latency:.2f}s attempts={attempts}"
            )

    os.makedirs("artifacts/nim-embedding-stress", exist_ok=True)
    path = "artifacts/nim-embedding-stress/results.json"
    with open(path, "w", encoding="utf-8") as handle:
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

    passed = sum(1 for item in results if item.correct)
    print(f"\nEmbedding retrieval: {passed}/{len(results)} correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
