from __future__ import annotations

import base64
import io
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODELS = [
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}
EXPECTED = {
    "organization_number": "923456789",
    "organization": "Nordlys Eksempel AS",
    "manager": "Kari Testperson",
    "postal_place": "Nannestad",
    "board_member": "Ola Kontroll",
}


@dataclass
class Result:
    model: str
    case: str
    transport_ok: bool
    json_ok: bool
    exact_fields: int
    total_fields: int
    latency_s: float
    attempts: int
    status_code: int | None = None
    finish_reason: str | None = None
    error: str | None = None
    output: str = ""


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_document(degraded: bool) -> bytes:
    image = Image.new("RGB", (1280, 900), "white")
    draw = ImageDraw.Draw(image)
    title = font(42, bold=True)
    heading = font(28, bold=True)
    body = font(27)
    small = font(24)

    draw.text((70, 55), "EKSEMPELREGISTER", fill="black", font=title)
    draw.line((70, 115, 1210, 115), fill="black", width=3)

    rows = [
        ("Organisasjonsnummer", "923 456 789"),
        ("Foretaksnavn", "Nordlys Eksempel AS"),
        ("Daglig leder", "Kari Testperson"),
        ("Forretningsadresse", "Teivegen 10"),
        ("Postnummer og sted", "2030 Nannestad"),
    ]
    y = 155
    for label, value in rows:
        draw.text((80, y), label + ":", fill="black", font=heading)
        draw.text((430, y), value, fill="black", font=body)
        y += 62

    table_top = 510
    draw.rectangle((80, table_top, 1200, 790), outline="black", width=3)
    draw.line((80, table_top + 65, 1200, table_top + 65), fill="black", width=2)
    draw.line((480, table_top, 480, 790), fill="black", width=2)
    draw.text((105, table_top + 15), "Rolle", fill="black", font=heading)
    draw.text((510, table_top + 15), "Navn", fill="black", font=heading)

    table_rows = [
        ("Daglig leder", "Kari Testperson"),
        ("Styremedlem", "Ola Kontroll"),
        ("Varamedlem", "Anne Eksempel"),
    ]
    y = table_top + 88
    for role, name in table_rows:
        draw.text((105, y), role, fill="black", font=small)
        draw.text((510, y), name, fill="black", font=small)
        y += 66

    draw.text(
        (80, 825),
        "Dette er syntetiske testdata og gjelder ingen virkelig person.",
        fill="black",
        font=small,
    )

    if degraded:
        image = image.resize((760, 534), Image.Resampling.LANCZOS)
        image = image.filter(ImageFilter.GaussianBlur(radius=0.65))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=48, optimize=True)
        return buffer.getvalue()

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def data_uri(data: bytes, degraded: bool) -> str:
    mime = "image/jpeg" if degraded else "image/png"
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def normalize_org(value: Any) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def score(output: str) -> tuple[bool, int]:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return False, 0
    if not isinstance(parsed, dict):
        return False, 0

    hits = 0
    for key, expected in EXPECTED.items():
        actual = parsed.get(key)
        if key == "organization_number":
            if normalize_org(actual) == expected:
                hits += 1
        elif str(actual or "").strip().casefold() == expected.casefold():
            hits += 1
    return True, hits


def sampling(model: str) -> tuple[float, float]:
    if "omni" in model:
        return 0.2, 1.0
    return 0.2, 1.0


def run_case(
    client: httpx.Client,
    api_key: str,
    model: str,
    case: str,
    degraded: bool,
) -> Result:
    image = make_document(degraded)
    prompt = (
        "Les dokumentbildet. Returner KUN gyldig JSON med feltene "
        "organization_number, organization, manager, postal_place og "
        "board_member. organization_number skal bare inneholde sifre. "
        "postal_place skal bare være stedsnavnet. board_member skal være "
        "personen med rollen Styremedlem. Ikke bruk kunnskap utenfor bildet."
    )
    temperature, top_p = sampling(model)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri(image, degraded)},
                    },
                ],
            }
        ],
        "max_tokens": 512,
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
                output = (message.get("content") or "").strip()
                json_ok, exact_fields = score(output)
                return Result(
                    model=model,
                    case=case,
                    transport_ok=True,
                    json_ok=json_ok,
                    exact_fields=exact_fields,
                    total_fields=len(EXPECTED),
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    status_code=200,
                    finish_reason=choice.get("finish_reason"),
                    output=output,
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                return Result(
                    model=model,
                    case=case,
                    transport_ok=True,
                    json_ok=False,
                    exact_fields=0,
                    total_fields=len(EXPECTED),
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    status_code=200,
                    error=f"unexpected response: {exc}",
                    output=response.text[:1000],
                )

        last_error = f"HTTP {response.status_code}: {response.text[:500]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        time.sleep(3.0)

    return Result(
        model=model,
        case=case,
        transport_ok=False,
        json_ok=False,
        exact_fields=0,
        total_fields=len(EXPECTED),
        latency_s=time.perf_counter() - started,
        attempts=2,
        status_code=last_status,
        error=last_error or "request failed",
    )


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")

    results: list[Result] = []
    cases = [("clean", False), ("degraded", True)]
    timeout = httpx.Timeout(45.0, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        for model in MODELS:
            for case, degraded in cases:
                result = run_case(client, api_key, model, case, degraded)
                results.append(result)
                print(
                    f"{model} [{case}] transport={result.transport_ok} "
                    f"json={result.json_ok} fields="
                    f"{result.exact_fields}/{result.total_fields} "
                    f"latency={result.latency_s:.2f}s "
                    f"attempts={result.attempts} error={result.error or '-'}"
                )
                if result.output:
                    print(result.output[:900].replace("\n", " "))

    os.makedirs("artifacts/nim-vision-document-probe", exist_ok=True)
    path = "artifacts/nim-vision-document-probe/results.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {"expected": EXPECTED, "results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print("\n| Model | Case | Exact fields | JSON | Latency |")
    print("|---|---|---:|---:|---:|")
    for result in results:
        print(
            f"| `{result.model}` | {result.case} | "
            f"{result.exact_fields}/{result.total_fields} | "
            f"{'PASS' if result.json_ok else 'FAIL'} | "
            f"{result.latency_s:.2f}s |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
