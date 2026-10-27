"""Optional local vision model (e.g. llava via Ollama) for rough year estimates."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime

import httpx

from .config import settings
from .model import Candidate

PROMPT = (
    "Estimate when this photo was taken, judging by image quality, colours, film grain, fashion, cars, "
    "technology and other visual clues. Answer ONLY with JSON: "
    '{"earliest_year": int, "latest_year": int, "best_year": int, "confidence": number 0-1, "reason": string}'
)


async def available() -> dict:
    if not settings.ollama_url:
        return {"configured": False}
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            r = await http.get(f"{settings.ollama_url}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError) as e:
        return {"configured": True, "reachable": False, "error": str(e)[:200]}
    return {"configured": True, "reachable": True, "model": settings.ollama_model,
            "installed": settings.ollama_model in models or any(m.startswith(settings.ollama_model) for m in models)}


async def estimate(jpeg: bytes, asset: dict) -> Candidate | None:
    body = {
        "model": settings.ollama_model,
        "prompt": PROMPT,
        "images": [base64.b64encode(jpeg).decode()],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    async with httpx.AsyncClient(timeout=180) as http:
        r = await http.post(f"{settings.ollama_url}/api/generate", json=body)
        r.raise_for_status()
    text = r.json().get("response", "")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m[0])
        best, lo, hi = int(data["best_year"]), int(data["earliest_year"]), int(data["latest_year"])
    except (ValueError, KeyError, TypeError):
        return None
    now = datetime.now().year
    if not (1850 <= lo <= best <= hi <= now):
        return None
    span = hi - lo
    precision = "year" if span <= 2 else "decade"
    conf = min(0.5, float(data.get("confidence") or 0.3)) * (1 if span <= 2 else 0.8)
    return Candidate(
        source="ollama", when=datetime(best, 7, 1, 12), precision=precision, confidence=round(conf, 2),
        explanation=f"Lokale KI ({settings.ollama_model}): {lo}–{hi}. {str(data.get('reason', ''))[:300]}",
        range_start=datetime(lo, 1, 1), range_end=datetime(hi, 12, 31, 23, 59),
    )
