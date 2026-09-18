from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODELS = [
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}
EXPECTED = {
    "organization_number": "923456789",
    "organization": "Skjærgårdsforvaltning Øst AS",
    "manager": "Åse Ødegård",
    "postal_place": "Værøy",
    "board_member": "Bjørn Sæther",
    "signature_rule": "styrets leder alene",
}
CASES = [
    "clean",
    "jpeg_small",
    "rotated",
    "low_contrast_noise",
    "stamped",
    "fax_hard",
]


@dataclass
class Result:
    model: str
    case: str
    transport_ok: bool
    json_ok: bool
    bare_json: bool
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
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        (
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
        ),
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_base_document() -> Image.Image:
    image = Image.new("RGB", (1500, 1120), "white")
    draw = ImageDraw.Draw(image)
    title = font(44, bold=True)
    section = font(30, bold=True)
    label = font(25, bold=True)
    body = font(25)
    small = font(20)

    draw.text((70, 42), "EKSEMPELREGISTER – FORETAKSOPPLYSNINGER", fill="black", font=title)
    draw.line((70, 105, 1430, 105), fill="black", width=3)

    draw.text((80, 135), "GJELDENDE OPPFØRING", fill="black", font=section)
    current_rows = [
        ("Organisasjonsnummer", "923 456 789"),
        ("Foretaksnavn", "Skjærgårdsforvaltning Øst AS"),
        ("Daglig leder", "Åse Ødegård"),
        ("Forretningsadresse", "Sjøfartsveien 7"),
        ("Postnummer og sted", "8063 Værøy"),
        ("Signatur", "Styrets leder alene"),
        ("Prokura", "Ingen registrert"),
    ]
    y = 190
    for key, value in current_rows:
        draw.text((90, y), f"{key}:", fill="black", font=label)
        draw.text((500, y), value, fill="black", font=body)
        y += 52

    table_top = 590
    draw.rectangle((80, table_top, 1420, 835), outline="black", width=3)
    draw.line((80, table_top + 58, 1420, table_top + 58), fill="black", width=2)
    draw.line((520, table_top, 520, 835), fill="black", width=2)
    draw.text((105, table_top + 12), "Rolle", fill="black", font=label)
    draw.text((550, table_top + 12), "Navn", fill="black", font=label)
    roles = [
        ("Daglig leder", "Åse Ødegård"),
        ("Styremedlem", "Bjørn Sæther"),
        ("Varamedlem", "Øyvind Kjær"),
    ]
    y = table_top + 78
    for role, name in roles:
        draw.text((105, y), role, fill="black", font=body)
        draw.text((550, y), name, fill="black", font=body)
        y += 58

    draw.rectangle((80, 870, 1420, 1030), outline=(100, 100, 100), width=2)
    draw.text((100, 890), "HISTORISK OPPFØRING – UTGÅTT", fill=(80, 80, 80), font=label)
    historical = (
        "Org.nr. 811 223 344 | Nordlys Eksempel AS | Daglig leder Kari Testperson | "
        "Sted Bærum | Styremedlem Ola Kontroll"
    )
    draw.text((100, 935), historical, fill=(90, 90, 90), font=small)
    draw.text(
        (80, 1065),
        "Syntetiske testdata. Dokumentet gjelder ingen virkelig person eller virksomhet.",
        fill=(60, 60, 60),
        font=small,
    )
    return image


def add_deterministic_noise(image: Image.Image, amount: int = 20) -> Image.Image:
    rng = random.Random(7421)
    noisy = image.convert("RGB")
    pixels = noisy.load()
    width, height = noisy.size
    for _ in range((width * height) // 85):
        x = rng.randrange(width)
        y = rng.randrange(height)
        base = pixels[x, y]
        delta = rng.randint(-amount, amount)
        pixels[x, y] = tuple(max(0, min(255, channel + delta)) for channel in base)
    return noisy


def add_stamp(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    stamp_font = font(96, bold=True)
    stamp = Image.new("RGBA", (900, 180), (255, 255, 255, 0))
    stamp_draw = ImageDraw.Draw(stamp)
    stamp_draw.rectangle((10, 20, 890, 160), outline=(145, 40, 40, 145), width=8)
    stamp_draw.text((70, 38), "KONTROLLERT KOPI", fill=(145, 40, 40, 125), font=stamp_font)
    stamp = stamp.rotate(17, expand=True, resample=Image.Resampling.BICUBIC)
    overlay.alpha_composite(stamp, dest=(320, 315))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def transform_document(case: str) -> tuple[bytes, str]:
    image = draw_base_document()
    mime = "image/png"

    if case == "jpeg_small":
        image = image.resize((780, 582), Image.Resampling.LANCZOS)
        image = image.filter(ImageFilter.GaussianBlur(radius=0.55))
        mime = "image/jpeg"
    elif case == "rotated":
        image = image.rotate(
            5.5,
            expand=True,
            fillcolor="white",
            resample=Image.Resampling.BICUBIC,
        )
        image = image.resize((1000, 820), Image.Resampling.LANCZOS)
        mime = "image/jpeg"
    elif case == "low_contrast_noise":
        image = ImageEnhance.Contrast(image).enhance(0.48)
        image = ImageEnhance.Brightness(image).enhance(1.08)
        image = add_deterministic_noise(image, amount=28)
        image = image.resize((900, 672), Image.Resampling.LANCZOS)
        mime = "image/jpeg"
    elif case == "stamped":
        image = add_stamp(image)
        image = image.resize((1050, 784), Image.Resampling.LANCZOS)
        mime = "image/jpeg"
    elif case == "fax_hard":
        image = image.convert("L")
        image = ImageEnhance.Contrast(image).enhance(0.62)
        image = image.filter(ImageFilter.GaussianBlur(radius=0.85))
        image = image.resize((660, 493), Image.Resampling.LANCZOS)
        image = add_deterministic_noise(image.convert("RGB"), amount=38)
        mime = "image/jpeg"

    buffer = io.BytesIO()
    if mime == "image/jpeg":
        quality = 34 if case == "fax_hard" else 48
        image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    else:
        image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), mime


def data_uri(data: bytes, mime: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def normalize_org(value: Any) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def extract_json(output: str) -> tuple[dict[str, Any] | None, bool]:
    stripped = output.strip()
    bare = True
    candidates = [stripped]
    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        candidates.append(fenced.group(1))
        bare = False
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        candidates.append(stripped[first : last + 1])
        if first != 0 or last != len(stripped) - 1:
            bare = False

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, bare
    return None, False


def score(output: str) -> tuple[bool, bool, int]:
    parsed, bare_json = extract_json(output)
    if parsed is None:
        return False, False, 0

    hits = 0
    for key, expected in EXPECTED.items():
        actual = parsed.get(key)
        if key == "organization_number":
            if normalize_org(actual) == expected:
                hits += 1
        elif str(actual or "").strip().casefold() == expected.casefold():
            hits += 1
    return True, bare_json, hits


def run_case(
    client: httpx.Client,
    api_key: str,
    model: str,
    case: str,
) -> Result:
    image, mime = transform_document(case)
    prompt = (
        "Les dokumentbildet nøye. Bruk KUN seksjonen 'GJELDENDE OPPFØRING'; "
        "ignorer historisk/utgått oppføring og eventuelle stempler. Returner KUN JSON "
        "med feltene organization_number, organization, manager, postal_place, "
        "board_member og signature_rule. organization_number skal bare ha sifre. "
        "postal_place skal bare være stedsnavnet. board_member skal være personen med "
        "rollen Styremedlem. signature_rule skal være teksten etter Signatur, med små "
        "bokstaver. Ikke fyll inn noe som ikke kan leses fra bildet."
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri(image, mime)},
                    },
                ],
            }
        ],
        "max_tokens": 650,
        "temperature": 0.2,
        "top_p": 1.0,
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
                json_ok, bare_json, exact_fields = score(output)
                return Result(
                    model=model,
                    case=case,
                    transport_ok=True,
                    json_ok=json_ok,
                    bare_json=bare_json,
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
                    bare_json=False,
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
        bare_json=False,
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
    timeout = httpx.Timeout(45.0, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        for model in MODELS:
            for case in CASES:
                result = run_case(client, api_key, model, case)
                results.append(result)
                print(
                    f"{model} [{case}] transport={result.transport_ok} "
                    f"json={result.json_ok} bare={result.bare_json} fields="
                    f"{result.exact_fields}/{result.total_fields} "
                    f"latency={result.latency_s:.2f}s attempts={result.attempts} "
                    f"error={result.error or '-'}"
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

    print("\n| Model | Case | Exact | JSON | Bare | Latency |")
    print("|---|---|---:|---:|---:|---:|")
    for result in results:
        print(
            f"| `{result.model}` | {result.case} | "
            f"{result.exact_fields}/{result.total_fields} | "
            f"{'PASS' if result.json_ok else 'FAIL'} | "
            f"{'YES' if result.bare_json else 'NO'} | "
            f"{result.latency_s:.2f}s |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
