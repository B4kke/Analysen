"""Real native OCR smoke on a synthetic public-document scan; no network or PII.

Run from repository root: python -m scripts.nb_native_ocr_smoke
"""
import hashlib
import io
import json

from PIL import Image, ImageDraw, ImageFont

from apps.api.app.services.nb_article_extract import extract_permitted_article

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def main() -> None:
    font = ImageFont.truetype(FONT, 48)
    image = Image.new("RGB", (1800, 1000), (235, 231, 219))
    draw = ImageDraw.Draw(image)
    phrase = "SOLENERGI PLAN"
    x, y = 120, 210
    draw.text((x, y), phrase, font=font, fill=(35, 35, 35))
    draw.text((x, y + 65), "Offentlig vedtak om energibruk.", font=font, fill=(35, 35, 35))
    draw.text((1200, 650), "ANNEN ARTIKKEL", font=font, fill=(35, 35, 35))
    x0, y0, x1, y1 = draw.textbbox((x, y), phrase, font=font)
    anchor = f"xywh={x0},{y0},{x1 - x0},{y1 - y0}"
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    page = raw.getvalue()
    result = extract_permitted_article(
        page,
        page_urn="URN:NBN:synthetic-public-doc",
        anchor_xywh=[anchor],
        target_expression=phrase,
    )
    assert result.target_validated, "native OCR could not validate synthetic title"
    assert result.crop_text and "SOLENERGI" in result.crop_text.upper()
    assert "ANNEN ARTIKKEL" not in result.crop_text.upper()
    assert result.page_sha256 == hashlib.sha256(page).hexdigest()
    assert result.region.crop_sha256 == hashlib.sha256(result.crop_bytes).hexdigest()
    with Image.open(io.BytesIO(result.crop_bytes)) as actual:
        expected = image.crop((
            result.region.x, result.region.y,
            result.region.x + result.region.w, result.region.y + result.region.h,
        ))
        assert actual.convert("RGB").tobytes() == expected.tobytes()
    print(json.dumps({
        "status": "passed",
        "algorithm": "local_anchor_v2",
        "page_pixels": image.width * image.height,
        "crop_pixels": result.region.w * result.region.h,
        "ocr_words": result.ocr_word_count,
        "ocr_mean_confidence": result.ocr_mean_confidence,
        "target_validated": result.target_validated,
        "crop_hash": result.region.crop_sha256,
    }, indent=2))


if __name__ == "__main__":
    main()
