from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import settings
from app.app_logger import log as app_log


@dataclass
class LLMResult:
    ok: bool
    text: str
    provider: str
    model: str
    error: str | None = None
    tried_fallback: bool = False


def _log(message: str) -> None:
    app_log("LLM", message)


def is_llm_configured() -> bool:
    provider = (settings.llm_provider or "mock").lower().strip()
    if provider == "groq":
        return bool(settings.groq_api_key)
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "gemini":
        return bool(settings.gemini_api_key)
    return bool(settings.groq_api_key or settings.gemini_api_key or settings.openai_api_key)


def provider_info() -> dict:
    provider = (settings.llm_provider or "mock").lower().strip()
    model = {
        "groq": settings.groq_model,
        "openai": settings.openai_model,
        "gemini": settings.gemini_model,
    }.get(provider, "mock")
    return {
        "provider": provider,
        "model": model,
        "configured": is_llm_configured(),
        "groq_configured": bool(settings.groq_api_key),
        "gemini_configured": bool(settings.gemini_api_key),
        "openai_configured": bool(settings.openai_api_key),
    }


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 1800) -> LLMResult:
    """Chama o LLM principal e tenta fallback configurado.

    Build 5.1: alguns ambientes bloqueiam Groq com HTTP 403/1010. A chamada agora usa
    headers mais completos e tenta fallback Gemini/OpenAI se as chaves existirem. Se nada
    funcionar, o agente usa fallback local seguro baseado apenas nos chunks recuperados.
    """
    provider = (settings.llm_provider or "mock").lower().strip()
    attempts: list[tuple[str, str, str, str]] = []

    if provider == "groq":
        attempts.append(("groq", settings.groq_api_key, settings.groq_model, "https://api.groq.com/openai/v1/chat/completions"))
        # fallback interno de modelo, útil quando modelo configurado está indisponível.
        if settings.groq_model != "llama-3.1-8b-instant":
            attempts.append(("groq", settings.groq_api_key, "llama-3.1-8b-instant", "https://api.groq.com/openai/v1/chat/completions"))
    elif provider == "openai":
        attempts.append(("openai", settings.openai_api_key, settings.openai_model, "https://api.openai.com/v1/chat/completions"))
    elif provider == "gemini":
        return _call_gemini(system_prompt, user_prompt, max_tokens=max_tokens)

    # Fallbacks opcionais fora do provider principal.
    if provider != "gemini" and settings.gemini_api_key:
        gem = _call_gemini(system_prompt, user_prompt, max_tokens=max_tokens)
        if gem.ok:
            gem.tried_fallback = True
            return gem
    if provider != "openai" and settings.openai_api_key:
        attempts.append(("openai", settings.openai_api_key, settings.openai_model, "https://api.openai.com/v1/chat/completions"))

    errors = []
    for idx, (prov, key, model, url) in enumerate(attempts):
        result = _call_openai_compatible(
            provider=prov,
            api_key=key,
            model=model,
            url=url,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )
        if result.ok:
            result.tried_fallback = idx > 0 or prov != provider
            return result
        errors.append(f"{prov}/{model}: {result.error}")

    return LLMResult(
        ok=False,
        text="",
        provider=provider,
        model={"groq": settings.groq_model, "openai": settings.openai_model}.get(provider, "mock"),
        error=" | ".join(errors) or "Nenhum provider de IA configurado.",
    )


def _call_openai_compatible(
    provider: str,
    api_key: str,
    model: str,
    url: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> LLMResult:
    if not api_key:
        return LLMResult(ok=False, text="", provider=provider, model=model, error=f"{provider.upper()}_API_KEY ausente")

    _log(f"Chamando provider={provider} model={model}")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.12,
        "top_p": 0.85,
        "max_tokens": max_tokens,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "StudyFlowPDFAI/5.1 (+https://localhost)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if not text:
                return LLMResult(ok=False, text="", provider=provider, model=model, error="LLM retornou resposta vazia")
            _log(f"Resposta recebida provider={provider} model={model} chars={len(text)}")
            return LLMResult(ok=True, text=text, provider=provider, model=model)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:1200]
        except Exception:
            detail = str(exc)
        _log(f"Erro HTTP provider={provider} status={exc.code} detail={detail}")
        hint = ""
        if exc.code == 403 and "1010" in detail:
            hint = " Bloqueio 1010 do gateway/WAF; tente Gemini/OpenAI como fallback ou teste no Railway."
        return LLMResult(ok=False, text="", provider=provider, model=model, error=f"HTTP {exc.code}: {detail}{hint}")
    except Exception as exc:
        _log(f"Erro provider={provider}: {exc}")
        return LLMResult(ok=False, text="", provider=provider, model=model, error=str(exc))


def _call_gemini(system_prompt: str, user_prompt: str, max_tokens: int = 1800) -> LLMResult:
    if not settings.gemini_api_key:
        return LLMResult(ok=False, text="", provider="gemini", model=settings.gemini_model, error="GEMINI_API_KEY ausente")

    model = settings.gemini_model or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.gemini_api_key}"
    _log(f"Chamando provider=gemini model={model}")
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.12,
            "topP": 0.85,
            "maxOutputTokens": max_tokens,
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "StudyFlowPDFAI/5.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            candidates = data.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                return LLMResult(ok=False, text="", provider="gemini", model=model, error="Gemini retornou resposta vazia")
            _log(f"Resposta recebida provider=gemini chars={len(text)}")
            return LLMResult(ok=True, text=text, provider="gemini", model=model)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:1200]
        except Exception:
            detail = str(exc)
        _log(f"Erro HTTP provider=gemini status={exc.code} detail={detail}")
        return LLMResult(ok=False, text="", provider="gemini", model=model, error=f"HTTP {exc.code}: {detail}")
    except Exception as exc:
        _log(f"Erro provider=gemini: {exc}")
        return LLMResult(ok=False, text="", provider="gemini", model=model, error=str(exc))
