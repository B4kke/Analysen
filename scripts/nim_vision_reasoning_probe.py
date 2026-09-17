from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODELS = [
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class Case:
    case_id: str
    image: bytes
    prompt: str
    expected: dict[str, Any]


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
    finish_reason: str | None = None
    error: str | None = None
    output: str = ""


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def as_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def invoice_case() -> Case:
    image = Image.new("RGB", (1150, 850), "white")
    draw = ImageDraw.Draw(image)
    title = font(42, True)
    head = font(25, True)
    body = font(24)
    draw.text((60, 45), "FAKTURA – SYNTETISK TEST", fill="black", font=title)
    draw.text((60, 115), "Kunde: Skjærgårdsforvaltning Øst AS", fill="black", font=body)
    draw.text((60, 155), "Fakturadato: 17.09.2026", fill="black", font=body)
    draw.text((60, 205), "Alle priser under er ekskl. mva.", fill="black", font=head)

    columns = [60, 530, 690, 875]
    top = 270
    draw.rectangle((50, top, 1100, 610), outline="black", width=3)
    for x in columns[1:]:
        draw.line((x, top, x, 610), fill="black", width=2)
    draw.line((50, top + 65, 1100, top + 65), fill="black", width=2)
    headers = ["Vare", "Antall", "Pris/stk", "Mva-sats"]
    for x, text in zip(columns, headers, strict=True):
        draw.text((x + 12, top + 16), text, fill="black", font=head)
    rows = [
        ("Arkivmappe blå", "3", "149,50 kr", "25 %"),
        ("Dokumentskanner", "2", "1 240,00 kr", "25 %"),
        ("Frakt og håndtering", "1", "189,00 kr", "25 %"),
    ]
    y = top + 92
    for row in rows:
        for x, text in zip(columns, row, strict=True):
            draw.text((x + 12, y), text, fill="black", font=body)
        y += 82
    draw.text(
        (60, 660),
        "Oppgave: beregn beløpene selv fra varelinjene. Ingen totalsum er trykt.",
        fill="black",
        font=body,
    )
    return Case(
        case_id="invoice_norwegian_decimal_math",
        image=as_png(image),
        prompt=(
            "Les fakturaen og regn ut summene. Norske komma er desimaltegn. Returner kun "
            "JSON med subtotal_ex_vat, vat_amount og total_inc_vat som tall i kroner. "
            "Mva skal beregnes med 25 %, og sluttbeløp rundes til to desimaler."
        ),
        expected={
            "subtotal_ex_vat": 3117.50,
            "vat_amount": 779.38,
            "total_inc_vat": 3896.88,
        },
    )


def ownership_case() -> Case:
    image = Image.new("RGB", (1200, 820), "white")
    draw = ImageDraw.Draw(image)
    title = font(38, True)
    box_head = font(28, True)
    body = font(25)
    draw.text((55, 35), "EIERSTRUKTUR – SYNTETISK", fill="black", font=title)

    boxes = {
        "person": (80, 150, 390, 290, "Åse Ødegård"),
        "holding": (480, 150, 820, 290, "Havblikk Holding AS"),
        "drift": (480, 510, 850, 650, "Skjærgård Drift AS"),
    }
    for left, top, right, bottom, text in boxes.values():
        draw.rounded_rectangle((left, top, right, bottom), radius=18, outline="black", width=3)
        draw.text((left + 20, top + 48), text, fill="black", font=box_head)

    draw.line((390, 220, 480, 220), fill="black", width=5)
    draw.polygon([(480, 220), (458, 207), (458, 233)], fill="black")
    draw.text((408, 175), "60 %", fill="black", font=body)

    draw.line((650, 290, 650, 510), fill="black", width=5)
    draw.polygon([(650, 510), (637, 486), (663, 486)], fill="black")
    draw.text((670, 385), "70 %", fill="black", font=body)

    draw.line((235, 290, 235, 580), fill="black", width=5)
    draw.line((235, 580, 480, 580), fill="black", width=5)
    draw.polygon([(480, 580), (455, 567), (455, 593)], fill="black")
    draw.text((260, 535), "10 % direkte", fill="black", font=body)

    draw.text(
        (70, 725),
        "Ingen andre eierlinjer finnes. Prosentene er eierandeler.",
        fill="black",
        font=body,
    )
    return Case(
        case_id="ownership_graph_effective_share",
        image=as_png(image),
        prompt=(
            "Les eierdiagrammet. Beregn Åse Ødegårds indirekte eierandel i Skjærgård "
            "Drift AS via Havblikk Holding AS, og legg til hennes direkte andel. Returner "
            "kun JSON med indirect_pct, direct_pct og effective_pct som tall."
        ),
        expected={"indirect_pct": 42.0, "direct_pct": 10.0, "effective_pct": 52.0},
    )


def timeline_case() -> Case:
    image = Image.new("RGB", (1250, 900), "white")
    draw = ImageDraw.Draw(image)
    title = font(38, True)
    head = font(24, True)
    body = font(23)
    draw.text((55, 35), "ROLLEHISTORIKK – SYNTETISK", fill="black", font=title)
    columns = [55, 285, 600, 840, 1040]
    top = 130
    draw.rectangle((45, top, 1200, 670), outline="black", width=3)
    for x in columns[1:]:
        draw.line((x, top, x, 670), fill="black", width=2)
    draw.line((45, top + 62, 1200, top + 62), fill="black", width=2)
    headers = ["Fra", "Til", "Rolle", "Person", "Status"]
    for x, text in zip(columns, headers, strict=True):
        draw.text((x + 9, top + 15), text, fill="black", font=head)

    rows = [
        ("01.03.2020", "31.01.2023", "Styreleder", "Ola Kontroll", "Avsluttet"),
        ("01.02.2023", "14.05.2025", "Styreleder", "Bjørn Sæther", "Avsluttet"),
        ("15.05.2025", "–", "Styreleder", "Åse Ødegård", "Aktiv"),
        ("12.08.2024", "–", "Daglig leder", "Øyvind Kjær", "Aktiv"),
        ("17.09.2026", "17.09.2026", "Varamedlem", "Kari Test", "Feilført"),
    ]
    y = top + 88
    for row in rows:
        for x, text in zip(columns, row, strict=True):
            draw.text((x + 9, y), text, fill="black", font=body)
        y += 86

    draw.text(
        (55, 730),
        "Merk: Feilførte rader skal ikke regnes som aktive verv.",
        fill="black",
        font=head,
    )
    return Case(
        case_id="role_timeline_with_decoy",
        image=as_png(image),
        prompt=(
            "Bruk tabellen. Finn aktiv styreleder per 17.09.2026 og datoen denne personen "
            "tiltrådte. Ignorer rader med status Feilført. Returner kun JSON med "
            "active_chair og chair_since i ISO-format YYYY-MM-DD."
        ),
        expected={"active_chair": "Åse Ødegård", "chair_since": "2025-05-15"},
    )


def extract_json(output: str) -> dict[str, Any] | None:
    stripped = output.strip()
    candidates = [stripped]
    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    )
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


def compare(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        return abs(float(actual) - float(expected)) < 0.011
    return str(actual or "").strip().casefold() == str(expected).strip().casefold()


def score(output: str, expected: dict[str, Any]) -> tuple[bool, int]:
    parsed = extract_json(output)
    if parsed is None:
        return False, 0
    hits = sum(
        1
        for key, value in expected.items()
        if key in parsed and compare(parsed[key], value)
    )
    return True, hits


def run_case(
    client: httpx.Client,
    api_key: str,
    model: str,
    case: Case,
) -> Result:
    encoded = base64.b64encode(case.image).decode("ascii")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": case.prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    },
                ],
            }
        ],
        "max_tokens": 1300,
        "temperature": 0.2,
        "top_p": 1.0,
        "stream": False,
    }
    if model.startswith("nvidia/nemotron-"):
        payload["chat_template_kwargs"] = {"enable_thinking": True}

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
                choice = body["choices"][0]
                message = choice["message"]
                output = (message.get("content") or "").strip()
                if not output:
                    output = (message.get("reasoning_content") or "").strip()
                json_ok, hits = score(output, case.expected)
                return Result(
                    model=model,
                    case_id=case.case_id,
                    transport_ok=True,
                    json_ok=json_ok,
                    exact_fields=hits,
                    total_fields=len(case.expected),
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    finish_reason=choice.get("finish_reason"),
                    output=output,
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                return Result(
                    model=model,
                    case_id=case.case_id,
                    transport_ok=True,
                    json_ok=False,
                    exact_fields=0,
                    total_fields=len(case.expected),
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    error=f"unexpected response: {exc}",
                    output=response.text[:1200],
                )

        last_error = f"HTTP {response.status_code}: {response.text[:500]}"
        if response.status_code not in TRANSIENT or attempt == 1:
            break
        time.sleep(3.0)

    return Result(
        model=model,
        case_id=case.case_id,
        transport_ok=False,
        json_ok=False,
        exact_fields=0,
        total_fields=len(case.expected),
        latency_s=time.perf_counter() - started,
        attempts=2,
        error=last_error or "request failed",
    )


def main() -> int:
    api_key = os.getenv("NIM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NIM_API_KEY is required")

    cases = [invoice_case(), ownership_case(), timeline_case()]
    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        for model in MODELS:
            for case in cases:
                result = run_case(client, api_key, model, case)
                results.append(result)
                print(
                    f"{model} [{case.case_id}] transport={result.transport_ok} "
                    f"json={result.json_ok} fields="
                    f"{result.exact_fields}/{result.total_fields} "
                    f"latency={result.latency_s:.2f}s attempts={result.attempts} "
                    f"finish={result.finish_reason or '-'} error={result.error or '-'}"
                )
                if result.output:
                    print(result.output[:1000].replace("\n", " "))

    os.makedirs("artifacts/nim-vision-reasoning", exist_ok=True)
    with open(
        "artifacts/nim-vision-reasoning/results.json",
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {"results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print("\n| Model | Case | Exact fields | Latency |")
    print("|---|---|---:|---:|")
    for result in results:
        print(
            f"| `{result.model}` | {result.case_id} | "
            f"{result.exact_fields}/{result.total_fields} | "
            f"{result.latency_s:.2f}s |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
