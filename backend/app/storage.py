from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.config import settings
from app.app_logger import log as app_log


def _log(message: str) -> None:
    app_log("storage", message)


def get_supabase_client():
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_service_key)


def normalize_storage_path(storage_name: str) -> str:
    """Garante um caminho seguro e compatível com Supabase Storage."""
    return storage_name.replace("\\", "/").strip("/")


def _content_type_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _upload_with_rest(local_path: Path, storage_name: str) -> str | None:
    """Upload direto pela API REST do Supabase Storage.

    Esse fallback é mais explícito que o supabase-py e mostra detalhes de erro.
    """
    base_url = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_bucket
    encoded_path = urllib.parse.quote(storage_name, safe="/")
    url = f"{base_url}/storage/v1/object/{bucket}/{encoded_path}"
    data = local_path.read_bytes()
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "apikey": settings.supabase_service_key,
        "Content-Type": _content_type_for(local_path),
        "x-upsert": "true",
    }

    def _send(method: str):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        return urllib.request.urlopen(req, timeout=60)

    try:
        with _send("POST") as response:
            body = response.read().decode("utf-8", errors="ignore")
            _log(f"Upload REST ok method=POST status={response.status} path={storage_name} body={body[:200]}")
            return storage_name
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        _log(f"Upload REST POST falhou status={exc.code} body={body[:500]}")
        # Se o objeto já existir ou o POST for recusado, tenta substituir com PUT.
        try:
            with _send("PUT") as response:
                put_body = response.read().decode("utf-8", errors="ignore")
                _log(f"Upload REST ok method=PUT status={response.status} path={storage_name} body={put_body[:200]}")
                return storage_name
        except urllib.error.HTTPError as put_exc:
            put_body = put_exc.read().decode("utf-8", errors="ignore")
            _log(f"Upload REST PUT falhou status={put_exc.code} body={put_body[:500]}")
            return None
        except Exception as put_exc:
            _log(f"Upload REST PUT indisponível: {put_exc}")
            return None
    except Exception as exc:
        _log(f"Upload REST indisponível: {exc}")
        return None


def upload_to_supabase_storage(local_path: Path, storage_name: str) -> str | None:
    """Envia arquivo para Supabase Storage quando as variáveis estão configuradas.

    Retorna o path salvo no bucket. Se falhar, retorna None e o sistema usa fallback local.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        _log("Supabase não configurado. Usando fallback local.")
        return None

    storage_name = normalize_storage_path(storage_name)
    _log(f"Tentando upload bucket={settings.supabase_bucket} path={storage_name} size={local_path.stat().st_size}")

    # 1) Primeira tentativa pelo cliente oficial.
    try:
        client = get_supabase_client()
        if client is not None:
            with local_path.open("rb") as file_obj:
                result = client.storage.from_(settings.supabase_bucket).upload(
                    path=storage_name,
                    file=file_obj,
                    file_options={
                        "content-type": _content_type_for(local_path),
                        "upsert": "true",
                    },
                )
            _log(f"Upload supabase-py finalizado path={storage_name} result={result}")
            return storage_name
    except Exception as exc:
        _log(f"Upload supabase-py falhou: {exc}")

    # 2) Segunda tentativa: REST direto, com logs mais detalhados.
    return _upload_with_rest(local_path, storage_name)


def delete_from_supabase_storage(storage_path: str | None) -> bool:
    """Remove arquivo do Supabase Storage quando possível.

    Retorna True se tentou/remover com sucesso. Em caso de falha, apenas loga e mantém o restante do delete.
    """
    if not storage_path:
        return False
    if not settings.supabase_url or not settings.supabase_service_key:
        _log("Delete ignorado: Supabase não configurado.")
        return False
    storage_path = normalize_storage_path(storage_path)
    try:
        client = get_supabase_client()
        if client is None:
            return False
        result = client.storage.from_(settings.supabase_bucket).remove([storage_path])
        _log(f"Delete Storage finalizado path={storage_path} result={result}")
        return True
    except Exception as exc:
        _log(f"Delete Storage falhou path={storage_path}: {exc}")
        return False


def health_storage() -> dict:
    try:
        client = get_supabase_client()
        if client is None:
            return {"ok": False, "configured": False, "bucket": settings.supabase_bucket, "error": "Supabase não configurado"}
        buckets = client.storage.list_buckets()
        names = []
        for b in buckets:
            name = getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None)
            if name:
                names.append(name)
        return {"ok": settings.supabase_bucket in names, "configured": True, "bucket": settings.supabase_bucket, "buckets": names}
    except Exception as exc:
        return {"ok": False, "configured": bool(settings.supabase_url and settings.supabase_service_key), "bucket": settings.supabase_bucket, "error": str(exc)}
