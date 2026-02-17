import json
from urllib import request, error

from config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    LLM_PROVIDER,
    LLM_MODEL,
    LLM_TEMPERATURE,
)

try:
    import anthropic
except ImportError:
    anthropic = None


class LLMError(Exception):
    pass


class LLMConfigError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


def generate_text(prompt: str, max_tokens: int = 512, temperature: float | None = None) -> str:
    provider = (LLM_PROVIDER or "").strip().lower()
    temp = LLM_TEMPERATURE if temperature is None else temperature

    if provider == "gemini":
        return _generate_gemini(prompt, max_tokens=max_tokens, temperature=temp)
    if provider == "anthropic":
        return _generate_anthropic(prompt, max_tokens=max_tokens, temperature=temp)
    raise LLMConfigError(f"Unsupported LLM_PROVIDER: {provider}")


def _generate_gemini(prompt: str, max_tokens: int, temperature: float) -> str:
    if not GEMINI_API_KEY:
        raise LLMConfigError("GEMINI_API_KEY is not set")

    model = _normalize_gemini_model(LLM_MODEL or "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "maxOutputTokens": int(max_tokens),
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        msg, status_code, status_text = _parse_google_error(body, fallback_code=exc.code)
        if _is_rate_limit(status_code, status_text, msg):
            raise LLMRateLimitError(msg)
        raise LLMError(msg)
    except error.URLError as exc:
        raise LLMError(f"Gemini API unreachable: {exc}")

    parsed = json.loads(raw)
    if parsed.get("error"):
        msg, status_code, status_text = _parse_google_error(raw, fallback_code=0)
        if _is_rate_limit(status_code, status_text, msg):
            raise LLMRateLimitError(msg)
        raise LLMError(msg)

    try:
        return parsed["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("Gemini API returned an unexpected response format")


def _generate_anthropic(prompt: str, max_tokens: int, temperature: float) -> str:
    if anthropic is None:
        raise LLMConfigError("Anthropic SDK is not installed")
    if not ANTHROPIC_API_KEY:
        raise LLMConfigError("ANTHROPIC_API_KEY is not set")

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as exc:
        msg = str(exc)
        if _is_rate_limit(0, "", msg):
            raise LLMRateLimitError(msg)
        raise LLMError(msg)


def _normalize_gemini_model(model: str) -> str:
    clean = (model or "").strip()
    if clean.startswith("models/"):
        return clean.split("/", 1)[1]
    return clean


def _parse_google_error(raw_body: str, fallback_code: int = 0) -> tuple[str, int, str]:
    try:
        data = json.loads(raw_body)
        err = data.get("error", {})
        return (
            str(err.get("message", "Google API error")),
            int(err.get("code") or fallback_code or 0),
            str(err.get("status", "")),
        )
    except Exception:
        return (raw_body.strip() or "Google API error", int(fallback_code or 0), "")


def _is_rate_limit(status_code: int, status_text: str, message: str) -> bool:
    text = f"{status_text} {message}".lower()
    if status_code == 429:
        return True
    return any(token in text for token in ("resource_exhausted", "rate limit", "quota", "too many requests"))
