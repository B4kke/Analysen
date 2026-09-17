from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml
from openai import OpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nim_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    model_config_path: Path = Path("./config/models.yaml")


TEXT_MODELS = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "google/gemma-4-31b-it",
]

VISION_MODELS = [
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]

EMBED_MODEL = "nvidia/nemotron-3-embed-1b"

NORWEGIAN_PROMPT = """Svar på norsk og vær presis.
Du gjør kildebevisst bakgrunnsanalyse. Tre kilder sier:
1) Ola Nordmann er styreleder i Eksempel AS fra 2024.
2) En eldre artikkel fra 2022 kaller ham daglig leder.
3) Et registeruttrekk fra 2026 viser Kari Hansen som daglig leder.
Oppsummer hva som kan hevdes sikkert, hva som er historisk, og hva som må verifiseres videre.
Ikke finn på fakta.
"""


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_text(client: OpenAI, model: str) -> None:
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Du er en norsk OSINT-analytiker. Skill fakta, historikk og usikkerhet.",
            },
            {"role": "user", "content": NORWEGIAN_PROMPT},
        ],
        temperature=0.2,
        max_tokens=700,
    )
    elapsed = time.perf_counter() - started
    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    total_tokens = getattr(usage, "total_tokens", None) if usage else None
    print(f"\n=== {model} ===")
    print(f"latency_total={elapsed:.2f}s total_tokens={total_tokens}")
    print(text.strip())


def run_vision(client: OpenAI, model: str, image_url: str) -> None:
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Beskriv bildet på norsk. Trekk ut synlig tekst nøyaktig. "
                            "Skill mellom det du faktisk ser og det du bare antar."
                        ),
                    },
                ],
            }
        ],
        temperature=0.2,
        max_tokens=900,
    )
    elapsed = time.perf_counter() - started
    text = response.choices[0].message.content or ""
    print(f"\n=== VISION {model} ===")
    print(f"latency_total={elapsed:.2f}s")
    print(text.strip())


def run_embedding(client: OpenAI) -> None:
    samples = [
        "Ola Nordmann er styreleder i Eksempel AS.",
        "Eksempel AS har Ola Nordmann som styreleder.",
        "Værmeldingen varsler regn i Oslo.",
    ]
    started = time.perf_counter()
    response = client.embeddings.create(model=EMBED_MODEL, input=samples)
    elapsed = time.perf_counter() - started
    dims = len(response.data[0].embedding) if response.data else 0
    print(f"\n=== EMBEDDING {EMBED_MODEL} ===")
    print(f"latency_total={elapsed:.2f}s vectors={len(response.data)} dims={dims}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test NVIDIA NIM models used by Analysen")
    parser.add_argument(
        "--suite",
        choices=["text", "vision", "embedding", "all"],
        default="text",
        help="Which model group to test. Default: text",
    )
    parser.add_argument(
        "--model",
        action="append",
        help="Override text model. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--image-url",
        help="Public image URL used by the vision suite.",
    )
    args = parser.parse_args()

    env = Env()
    if not env.nim_api_key:
        raise SystemExit(
            "NIM_API_KEY mangler. Kopier .env.example til .env og sett NIM_API_KEY der."
        )

    # Parse model config as a cheap syntax/config smoke check before inference.
    config = load_yaml(env.model_config_path)
    if not config.get("roles"):
        raise SystemExit(f"Ingen model roles funnet i {env.model_config_path}")

    client = OpenAI(base_url=env.nim_base_url, api_key=env.nim_api_key)

    if args.suite in {"text", "all"}:
        for model in args.model or TEXT_MODELS:
            try:
                run_text(client, model)
            except Exception as exc:  # noqa: BLE001 - smoke test must continue across models
                print(f"\n=== {model} FAILED ===\n{type(exc).__name__}: {exc}")

    if args.suite in {"vision", "all"}:
        if not args.image_url:
            print("\nVision hoppet over: bruk --image-url <public-url>.")
        else:
            for model in VISION_MODELS:
                try:
                    run_vision(client, model, args.image_url)
                except Exception as exc:  # noqa: BLE001
                    print(f"\n=== VISION {model} FAILED ===\n{type(exc).__name__}: {exc}")

    if args.suite in {"embedding", "all"}:
        try:
            run_embedding(client)
        except Exception as exc:  # noqa: BLE001
            print(f"\n=== EMBEDDING FAILED ===\n{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
