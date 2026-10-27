"""On-demand date estimation with Claude (vision + all context ImmichChrono collected)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime

import anthropic

from .config import settings
from .model import PRECISIONS, Candidate

# USD per million tokens (input, output).
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
MODELS = tuple(PRICES)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Conservative per-image estimate: a ~1440px preview is ≈1.6k tokens, plus prompt and
# context; output includes the model's (always-on) thinking.
EST_IMAGE_TOKENS = 1600
EST_PROMPT_TOKENS = 900
EST_OUTPUT_TOKENS = 2500
MAX_TOKENS = 6000

SYSTEM = """You are a photo archivist helping to restore the correct capture date of photos and videos in a \
personal library. The stored date of this item is suspected to be wrong (missing metadata, a reset camera clock, \
a scanned print, a messenger copy, ...).

Use every clue: visible date imprints, documents, screens, calendars, signs, seasons and weather, \
lighting, clothing and hairstyles, vehicles and licence plates, technology, image and film quality, aspect ratio, \
colour cast of old prints, and the context given below (file name, folders, camera, recognised text, people with \
their birth dates and therefore apparent ages, dates of visually similar photos and of neighbouring files).

Be honest about uncertainty: give the narrowest range you can justify, never a fake precise time. If the context \
contains a strong signal (e.g. a readable date imprint) prefer it over stylistic guesses. Write the reasoning in \
German, at most five sentences."""

SCHEMA = {
    "type": "object",
    "properties": {
        "earliest": {"type": "string", "description": "Earliest plausible date, YYYY-MM-DD"},
        "latest": {"type": "string", "description": "Latest plausible date, YYYY-MM-DD"},
        "best_guess": {"type": "string", "description": "Most likely date/time, YYYY-MM-DDTHH:MM:SS (local)"},
        "precision": {"type": "string", "enum": ["minute", "hour", "day", "month", "year", "decade"]},
        "confidence": {"type": "number", "description": "0 to 1"},
        "reasoning": {"type": "string"},
    },
    "required": ["earliest", "latest", "best_guess", "precision", "confidence", "reasoning"],
    "additionalProperties": False,
}


@dataclass
class Result:
    candidate: Candidate | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    error: str | None = None


def model_name(requested: str | None) -> str:
    return requested if requested in PRICES else (settings.claude_model if settings.claude_model in PRICES
                                                  else "claude-opus-5-5")


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
    return input_tokens / 1e6 * pin + output_tokens / 1e6 * pout


def estimate(model: str, n: int, context_chars: int = 1500) -> dict:
    per_in = EST_IMAGE_TOKENS + EST_PROMPT_TOKENS + context_chars // 3
    per_image = cost(model, per_in, EST_OUTPUT_TOKENS)
    return {
        "model": model, "count": n, "per_image_usd": round(per_image, 4), "total_usd": round(per_image * n, 4),
        "max_per_image_usd": round(cost(model, per_in, MAX_TOKENS), 4),
    }


def context_text(asset: dict, ctx: dict) -> str:
    exif = asset.get("exifInfo") or {}
    lines = [
        f"File name: {asset.get('originalFileName')}",
        f"Original path: {asset.get('originalPath')}",
        f"Type: {asset.get('type')}",
        f"Currently stored date (suspect): {asset.get('localDateTime')}",
        f"File timestamps: created {asset.get('fileCreatedAt')}, modified {asset.get('fileModifiedAt')}",
        f"Uploaded to library: {asset.get('createdAt')}",
        f"Camera: {exif.get('make') or '-'} {exif.get('model') or ''}".rstrip(),
    ]
    if exif.get("city") or exif.get("country"):
        place = ", ".join(x for x in (exif.get("city"), exif.get("state"), exif.get("country")) if x)
        lines.append(f"Location: {place}")
    if exif.get("description"):
        lines.append(f"Description: {exif['description']}")
    people = [p for p in asset.get("people") or [] if p.get("name")]
    if people:
        lines.append("Recognised people: " + "; ".join(
            f"{p['name']} (born {p['birthDate']})" if p.get("birthDate") else p["name"] for p in people))
    if ctx.get("issues"):
        lines.append("Detected problems: " + ", ".join(ctx["issues"]))
    if ctx.get("ocr"):
        lines.append(f"Text recognised in the image (OCR): {ctx['ocr'][:1500]}")
    if ctx.get("similar"):
        lines.append("Dates of visually similar photos with reliable dates: " + ", ".join(ctx["similar"][:10]))
    if ctx.get("neighbours"):
        lines.append("Files uploaded right before/after it (name: date): " + "; ".join(ctx["neighbours"][:10]))
    if ctx.get("candidates"):
        lines.append("Other hints found so far: " + "; ".join(ctx["candidates"][:8]))
    return "\n".join(lines)


async def analyze(jpeg: bytes, asset: dict, ctx: dict, model: str) -> Result:
    if not settings.anthropic_api_key:
        return Result(None, 0, 0, 0.0, model, "ANTHROPIC_API_KEY ist nicht gesetzt")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=3)
    params: dict = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(jpeg).decode()}},
                {"type": "text", "text": "Context:\n" + context_text(asset, ctx)
                 + "\n\nWhen was this photo most likely taken?"},
            ],
        }],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }
    if "haiku" not in model:
        params["output_config"]["effort"] = "medium"
    try:
        # Server-side refusal fallback is on: a declined request is retried on Anthropic's
        # recommended fallback model inside the same call.
        response = await client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
    except anthropic.APIStatusError as e:
        return Result(None, 0, 0, 0.0, model, f"Claude-API-Fehler {e.status_code}: {e.message}"[:300])
    except anthropic.APIConnectionError:
        return Result(None, 0, 0, 0.0, model, "Claude-API nicht erreichbar")
    finally:
        await client.close()

    usage = response.usage
    tokens_in = (usage.input_tokens or 0) + (usage.cache_creation_input_tokens or 0) + (
        usage.cache_read_input_tokens or 0)
    tokens_out = usage.output_tokens or 0
    spent = cost(response.model if response.model in PRICES else model, tokens_in, tokens_out)
    result = Result(None, tokens_in, tokens_out, spent, response.model)
    if response.stop_reason == "refusal":
        result.error = "Claude hat die Anfrage abgelehnt"
        return result
    if response.stop_reason == "max_tokens":
        result.error = "Antwort wurde abgeschnitten"
        return result
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        result.candidate = parse_answer(json.loads(text))
    except (ValueError, KeyError, TypeError) as e:
        result.error = f"Antwort nicht lesbar: {e}"
    return result


def parse_answer(data: dict) -> Candidate | None:
    best = datetime.fromisoformat(str(data["best_guess"])[:19])
    earliest = date.fromisoformat(str(data["earliest"])[:10])
    latest = date.fromisoformat(str(data["latest"])[:10])
    precision = data["precision"] if data["precision"] in PRECISIONS else "year"
    if precision in ("day", "month", "year", "decade"):
        best = best.replace(hour=12, minute=0, second=0) if best.hour == 0 and best.minute == 0 else best
    conf = max(0.0, min(0.9, float(data["confidence"])))
    return Candidate(
        source="claude", when=best, precision=precision, confidence=round(conf, 2),
        explanation=f"Claude: {str(data['reasoning'])[:800]}",
        range_start=datetime.combine(earliest, datetime.min.time()),
        range_end=datetime.combine(latest, datetime.max.time()).replace(microsecond=0),
    )
