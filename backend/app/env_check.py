from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.database import fetch_one, fetch_all, health_database, is_postgres
from app.storage import health_storage
from app.llm_client import provider_info


def _secret_meta(value: str | None) -> dict[str, Any]:
    text = value or ""
    return {
        "configured": bool(text.strip()),
        "length": len(text),
        "preview": _preview(text),
    }


def _preview(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def _is_placeholder(value: str | None) -> bool:
    text = (value or "").lower().strip()
    if not text:
        return False
    placeholders = (
        "change_me", "sua_chave", "cole_", "your-", "your_", "example",
        "senha", "password", "placeholder", "dev_", "troque",
    )
    return any(token in text for token in placeholders)


def _result(name: str, ok: bool, message: str, severity: str = "error", meta: dict | None = None) -> dict:
    return {
        "name": name,
        "ok": ok,
        "severity": "ok" if ok else severity,
        "message": message,
        "meta": meta or {},
    }


def _check_database_url() -> dict:
    url = settings.database_url or ""
    parsed = urlparse(url)
    meta = {
        "configured": bool(url),
        "engine": "postgres/supabase" if url.startswith(("postgresql://", "postgres://")) else "sqlite" if url.startswith("sqlite") else "unknown",
        "host": parsed.hostname or "local",
        "database": (parsed.path or "").lstrip("/") or "local",
    }
    if not url:
        return _result("DATABASE_URL", False, "DATABASE_URL não configurado.", meta=meta)
    if settings.app_env == "production" and not url.startswith(("postgresql://", "postgres://")):
        return _result("DATABASE_URL", False, "Em produção, use PostgreSQL/Supabase. Não use SQLite no Railway.", meta=meta)
    if "[YOUR-PASSWORD]" in url or _is_placeholder(url):
        return _result("DATABASE_URL", False, "DATABASE_URL parece conter placeholder ou senha não trocada.", meta=meta)
    return _result("DATABASE_URL", True, "DATABASE_URL configurado.", meta=meta)


def _check_jwt_secret() -> dict:
    value = settings.jwt_secret or ""
    meta = _secret_meta(value)
    if not value:
        return _result("JWT_SECRET", False, "JWT_SECRET não configurado.", meta=meta)
    if value == "change_me_in_production" or _is_placeholder(value):
        return _result("JWT_SECRET", False, "JWT_SECRET ainda parece ser padrão/placeholder.", meta=meta)
    if len(value) < 32:
        return _result("JWT_SECRET", False, "JWT_SECRET está curto. Use uma chave com pelo menos 32 caracteres.", severity="warning", meta=meta)
    return _result("JWT_SECRET", True, "JWT_SECRET configurado.", meta=meta)


def _check_supabase_url() -> dict:
    value = settings.supabase_url or ""
    parsed = urlparse(value)
    meta = {"configured": bool(value), "host": parsed.hostname or ""}
    if not value:
        return _result("SUPABASE_URL", False, "SUPABASE_URL não configurado.", meta=meta)
    if not value.startswith("https://"):
        return _result("SUPABASE_URL", False, "SUPABASE_URL deve começar com https://.", meta=meta)
    if "supabase.co" not in value:
        return _result("SUPABASE_URL", False, "SUPABASE_URL não parece ser uma URL padrão do Supabase.", severity="warning", meta=meta)
    return _result("SUPABASE_URL", True, "SUPABASE_URL configurado.", meta=meta)


def _check_supabase_key(name: str, value: str | None, expected_role: str | None = None) -> dict:
    text = value or ""
    meta = _secret_meta(text)
    if not text:
        return _result(name, False, f"{name} não configurado.", meta=meta)
    if _is_placeholder(text):
        return _result(name, False, f"{name} parece conter placeholder.", meta=meta)
    if not text.startswith("eyJ") or text.count(".") != 2:
        return _result(name, False, f"{name} não parece ser um JWT válido do Supabase.", severity="warning", meta=meta)
    if expected_role and expected_role not in text:
        # O JWT normalmente vem base64url, então isso nem sempre aparece em texto puro.
        meta["role_hint"] = "não validado por base64"
    return _result(name, True, f"{name} configurado.", meta=meta)


def _check_bucket() -> dict:
    value = settings.supabase_bucket or ""
    meta = {"configured": bool(value), "bucket": value}
    if not value:
        return _result("SUPABASE_BUCKET", False, "SUPABASE_BUCKET não configurado.", meta=meta)
    return _result("SUPABASE_BUCKET", True, "SUPABASE_BUCKET configurado.", meta=meta)


def _check_llm() -> dict:
    provider = (settings.llm_provider or "").lower().strip()
    meta = {"provider": provider, "model": ""}
    if provider == "groq":
        meta["model"] = settings.groq_model
        key = settings.groq_api_key or ""
        meta.update(_secret_meta(key))
        if not key:
            return _result("GROQ_API_KEY", False, "LLM_PROVIDER=groq, mas GROQ_API_KEY não está configurada.", meta=meta)
        if _is_placeholder(key):
            return _result("GROQ_API_KEY", False, "GROQ_API_KEY parece conter placeholder.", meta=meta)
        if not key.startswith("gsk_"):
            return _result("GROQ_API_KEY", False, "GROQ_API_KEY não parece ser uma chave Groq válida; normalmente começa com gsk_.", severity="warning", meta=meta)
        if not settings.groq_model:
            return _result("GROQ_MODEL", False, "GROQ_MODEL não configurado.", meta=meta)
        return _result("GROQ_API_KEY", True, "Groq configurado.", meta=meta)
    if provider == "openai":
        key = settings.openai_api_key or ""
        meta.update(_secret_meta(key))
        meta["model"] = settings.openai_model
        return _result("OPENAI_API_KEY", bool(key), "OpenAI configurado." if key else "OPENAI_API_KEY não configurada.", meta=meta)
    if provider == "gemini":
        key = settings.gemini_api_key or ""
        meta.update(_secret_meta(key))
        meta["model"] = settings.gemini_model
        return _result("GEMINI_API_KEY", bool(key), "Gemini configurado." if key else "GEMINI_API_KEY não configurada.", meta=meta)
    return _result("LLM_PROVIDER", False, "LLM_PROVIDER inválido. Use groq, openai ou gemini.", meta=meta)


def _check_upload_config() -> list[dict]:
    checks = []
    checks.append(_result("MAX_UPLOAD_SIZE_MB", settings.max_upload_size_mb > 0, f"MAX_UPLOAD_SIZE_MB={settings.max_upload_size_mb}", meta={"value": settings.max_upload_size_mb}))
    checks.append(_result("OCR_MAX_PAGES", settings.ocr_max_pages > 0, f"OCR_MAX_PAGES={settings.ocr_max_pages}", meta={"value": settings.ocr_max_pages}))
    checks.append(_result("OCR_LANGUAGES", bool(settings.ocr_languages), f"OCR_LANGUAGES={settings.ocr_languages}", meta={"value": settings.ocr_languages}))
    checks.append(_result("OCR_RENDER_SCALE", settings.ocr_render_scale > 0, f"OCR_RENDER_SCALE={settings.ocr_render_scale}", meta={"value": settings.ocr_render_scale}))
    return checks


def env_check() -> dict:
    checks = [
        _check_database_url(),
        _check_jwt_secret(),
        _check_supabase_url(),
        _check_supabase_key("SUPABASE_SERVICE_KEY", settings.supabase_service_key, "service_role"),
        _check_supabase_key("SUPABASE_ANON_KEY", settings.supabase_anon_key, "anon"),
        _check_bucket(),
        _check_llm(),
        *_check_upload_config(),
    ]
    errors = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
    return {
        "ok": not errors,
        "environment": settings.app_env,
        "debug": settings.app_debug,
        "log_level": settings.log_level,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "errors": len(errors),
            "warnings": len(warnings),
            "ready_for_deploy": not errors and settings.app_env == "production",
        },
        "next_steps": _next_steps(errors, warnings),
    }


def _next_steps(errors: list[dict], warnings: list[dict]) -> list[str]:
    steps = []
    for item in errors[:8]:
        steps.append(f"Corrigir {item['name']}: {item['message']}")
    for item in warnings[:4]:
        steps.append(f"Revisar {item['name']}: {item['message']}")
    if not steps:
        steps.append("Variáveis essenciais parecem configuradas. Rode /api/health/runtime-check para testar serviços externos.")
    return steps



def _column_exists(table: str, column: str) -> dict:
    try:
        if is_postgres():
            row = fetch_one(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ? AND column_name = ?
                """,
                (table, column),
            )
        else:
            rows = fetch_all(f"PRAGMA table_info({table})")
            row = next((r for r in rows if r.get("name") == column), None)
        return {"table": table, "column": column, "ok": bool(row)}
    except Exception as exc:
        return {"table": table, "column": column, "ok": False, "error": str(exc)}


def schema_check() -> dict:
    required = {
        "profiles": ["id", "email", "password_hash"],
        "notebooks": ["id", "user_id", "title"],
        "documents": ["id", "user_id", "notebook_id", "filename", "original_filename", "file_type", "file_size", "storage_bucket", "storage_path", "local_path", "status", "character_count", "chunk_count"],
        "document_chunks": ["id", "document_id", "user_id", "notebook_id", "chunk_index", "content", "page_number", "character_count"],
        "chat_messages": ["id", "user_id", "notebook_id", "role", "content", "metadata"],
        "generated_materials": ["id", "user_id", "notebook_id", "document_id", "type", "title", "content", "metadata"],
        "quiz_attempts": ["id", "user_id", "notebook_id", "title", "score", "total_questions", "answered", "answers"],
    } if is_postgres() else {}
    columns = []
    for table, names in required.items():
        for column in names:
            columns.append(_column_exists(table, column))
    missing = [c for c in columns if not c.get("ok")]
    return {"ok": not missing, "missing_count": len(missing), "missing": missing[:30]}

def _table_count(table: str) -> dict:
    try:
        row = fetch_one(f"SELECT count(*) AS total FROM {table}")
        return {"table": table, "ok": True, "count": row.get("total", 0) if row else 0}
    except Exception as exc:
        return {"table": table, "ok": False, "error": str(exc)}


def runtime_check() -> dict:
    db = health_database()
    storage = health_storage()
    llm = provider_info()
    tables = []
    if is_postgres():
        tables = [_table_count(t) for t in ["profiles", "notebooks", "documents", "document_chunks", "chat_messages", "generated_materials", "quiz_attempts"]]
    else:
        tables = [_table_count(t) for t in ["users", "notebooks", "documents", "document_chunks", "chat_messages", "generated_materials", "quiz_attempts"]]
    schema = schema_check() if is_postgres() else {"ok": True, "missing_count": 0, "missing": []}
    ok = bool(db.get("ok")) and bool(storage.get("ok")) and bool(llm.get("configured")) and all(t.get("ok") for t in tables) and bool(schema.get("ok"))
    return {
        "ok": ok,
        "database": db,
        "storage": storage,
        "llm": llm,
        "tables": tables,
        "schema": schema,
        "notes": [
            "Este endpoint não expõe chaves reais.",
            "Use /api/health/llm/test para uma chamada curta real ao provider de IA.",
        ],
    }
