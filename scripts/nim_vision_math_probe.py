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
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504, 529}


@dataclass
class Case:
    case_id: str
    image: bytes
    prompt: str
    expected: dict[str, float]


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


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def table(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    widths: list[int],
) -> Image.Image:
    width = sum(widths) + 100
    row_height = 76
    top = 135
    height = top + row_height * (len(rows) + 1) + 120
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((45, 35), title, fill="black", font=font(38, True))
    x_positions = [50]
    for cell_width in widths[:-1]:
        x_positions.append(x_positions[-1] + cell_width)
    right = 50 + sum(widths)
    bottom = top + row_height * (len(rows) + 1)
    draw.rectangle((50, top, right, bottom), outline="black", width=3)
    for x in x_positions[1:]:
        draw.line((x, top, x, bottom), fill="black", width=2)
    for row_index in range(1, len(rows) + 1):
        y = top + row_height * row_index
        draw.line((50, y, right, y), fill="black", width=2)
    for x, header in zip(x_positions, headers, strict=True):
        draw.text((x + 10, top + 20), header, fill="black", font=font(23, True))
    for row_index, row in enumerate(rows, start=1):
        y = top + row_height * row_index + 20
        for x, value in zip(x_positions, row, strict=True):
            draw.text((x + 10, y), value, fill="black", font=font(23))
    return image


def invoice_case() -> Case:
    image = table(
        "FAKTURA – priser ekskl. mva.",
        ["Vare", "Antall", "Pris/stk", "Mva"],
        [
            ["Arkivmappe blå", "3", "149,50 kr", "25 %"],
            ["Dokumentskanner", "2", "1 240,00 kr", "25 %"],
            ["Frakt", "1", "189,00 kr", "25 %"],
        ],
        [430, 150, 240, 160],
    )
    return Case(
        case_id="invoice_vat",
        image=png(image),
        prompt=(
            "Regn fra varelinjene i bildet. Norske komma er desimaltegn. Returner KUN JSON "
            "med subtotal_ex_vat, vat_amount og total_inc_vat. Mva er 25 %. Rund til to "
            "desimaler først på sluttverdiene."
        ),
        expected={
            "subtotal_ex_vat": 3117.50,
            "vat_amount": 779.38,
            "total_inc_vat": 3896.88,
        },
    )


def accounts_case() -> Case:
    image = table(
        "RESULTATUTDRAG – beløp i kroner",
        ["Post", "2025", "2026"],
        [
            ["Driftsinntekter", "1 250 000,00", "1 537 500,00"],
            ["Driftskostnader", "1 100 000,00", "1 200 000,00"],
            ["Driftsresultat", "150 000,00", "337 500,00"],
        ],
        [450, 300, 300],
    )
    return Case(
        case_id="accounts_growth_margin",
        image=png(image),
        prompt=(
            "Bruk tabellen. Returner KUN JSON med revenue_growth_pct fra 2025 til 2026 og "
            "operating_margin_2026_pct = driftsresultat/driftsinntekter*100. Rund begge til "
            "to desimaler."
        ),
        expected={"revenue_growth_pct": 23.00, "operating_margin_2026_pct": 21.95},
    )


def ledger_case() -> Case:
    image = table(
        "KONTOUTDRAG – SYNTETISK",
        ["Dato", "Tekst", "Beløp"],
        [
            ["01.09.2026", "Innbetaling", "+12 500,00"],
            ["03.09.2026", "Utbetaling", "-2 499,50"],
            ["07.09.2026", "Utbetaling", "-1 250,25"],
            ["12.09.2026", "Innbetaling", "+3 100,00"],
            ["15.09.2026", "Utbetaling", "-900,25"],
        ],
        [250, 450, 280],
    )
    return Case(
        case_id="ledger_signed_amounts",
        image=png(image),
        prompt=(
            "Summer beløpene i bildet. Returner KUN JSON med credits_total som summen av "
            "positive beløp, debits_total som positiv absolutt sum av negative beløp, og "
            "net_change som credits_total minus debits_total."
        ),
        expected={"credits_total": 15600.00, "debits_total": 4650.00, "net_change": 10950.00},
    )


def extract_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
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


def compare_number(actual: Any, expected: float) -> bool:
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    return abs(float(actual) - expected) <= 0.011


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
        "max_tokens": 1200,
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
                message = body["choices"][0]["message"]
                output = (message.get("content") or "").strip()
                if not output:
                    output = (message.get("reasoning_content") or "").strip()
                parsed = extract_json(output)
                if parsed is None:
                    return Result(
                        model=model,
                        case_id=case.case_id,
                        transport_ok=True,
                        json_ok=False,
                        exact_fields=0,
                        total_fields=len(case.expected),
                        latency_s=time.perf_counter() - started,
                        attempts=attempt + 1,
                        error="no JSON object in response",
                        output=output,
                    )
                hits = sum(
                    1
                    for key, value in case.expected.items()
                    if key in parsed and compare_number(parsed[key], value)
                )
                return Result(
                    model=model,
                    case_id=case.case_id,
                    transport_ok=True,
                    json_ok=True,
                    exact_fields=hits,
                    total_fields=len(case.expected),
                    latency_s=time.perf_counter() - started,
                    attempts=attempt + 1,
                    output=output,
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = f"bad response: {exc}"
                break
        last_error = f"HTTP {response.status_code}: {response.text[:400]}"
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
    cases = [invoice_case(), accounts_case(), ledger_case()]
    results: list[Result] = []
    with httpx.Client(timeout=httpx.Timeout(50.0, connect=10.0)) as client:
        for model in MODELS:
            for case in cases:
                result = run_case(client, api_key, model, case)
                results.append(result)
                print(
                    f"{model} [{case.case_id}] fields="
                    f"{result.exact_fields}/{result.total_fields} "
                    f"json={result.json_ok} latency={result.latency_s:.2f}s "
                    f"attempts={result.attempts} error={result.error or '-'}"
                )
                if result.output:
                    print(result.output[:900].replace("\n", " "))

    os.makedirs("artifacts/nim-vision-math", exist_ok=True)
    with open("artifacts/nim-vision-math/results.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"results": [asdict(item) for item in results]},
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Benchmark trigger: 2026-09-17T15:08Z
