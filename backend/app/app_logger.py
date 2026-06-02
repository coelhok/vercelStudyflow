from __future__ import annotations

import re
from app.config import settings

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
_ERROR_HINTS = (
    "erro", "error", "falhou", "falha", "exception", "traceback", "unauthorized",
    "forbidden", "indisponivel", "indisponível", "violates", "constraint", "invalid",
)
_SENSITIVE_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I), "Bearer ***"),
    (re.compile(r"(apikey|api_key|service_key|token|jwt|password|senha)=([^\s&]+)", re.I), r"\1=***"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "***jwt***"),
]


def _current_level() -> str:
    return (getattr(settings, "log_level", "debug") or "debug").lower().strip()


def _infer_level(message: str) -> str:
    text = (message or "").lower()
    if any(hint in text for hint in _ERROR_HINTS):
        return "error"
    return "debug"


def _enabled(level: str) -> bool:
    if getattr(settings, "app_debug", False):
        return True
    configured = _current_level()
    if configured == "silent":
        return False
    return _LEVELS.get(level, 10) >= _LEVELS.get(configured, 20)


def sanitize(value: object) -> str:
    text = str(value)
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def log(prefix: str, message: object, level: str | None = None) -> None:
    final_level = (level or _infer_level(str(message))).lower()
    if not _enabled(final_level):
        return
    print(f"[{prefix}] {sanitize(message)}", flush=True)


def debug(prefix: str, message: object) -> None:
    log(prefix, message, "debug")


def info(prefix: str, message: object) -> None:
    log(prefix, message, "info")


def error(prefix: str, message: object) -> None:
    log(prefix, message, "error")
