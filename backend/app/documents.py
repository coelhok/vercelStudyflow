from pathlib import Path
import os
from time import time
import re
import unicodedata
from uuid import uuid4
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request

from app.config import settings
from app.app_logger import log as app_log
from app.database import execute, execute_many, fetch_all, fetch_one, is_postgres
from app.file_reader import read_file, chunk_text
from app.auth import get_current_user_id
from pydantic import BaseModel

from app.storage import upload_to_supabase_storage, delete_from_supabase_storage, create_signed_upload_url, download_from_supabase_storage

router = APIRouter()
UPLOAD_DIR = Path("/tmp/studyflow_uploads") if os.getenv("VERCEL") else Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED = {".pdf", ".docx", ".txt"}
MAX_UPLOAD_MB = settings.max_upload_size_mb
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def _safe_storage_filename(filename: str) -> str:
    """Sanitiza nomes para Supabase Storage.

    Evita InvalidKey com espaços, acentos, cedilha e símbolos. Mantém extensão.
    Ex.: "Guia de Inteligência Artificial.pdf" -> "guia_de_inteligencia_artificial.pdf"
    """
    raw = Path(filename or "arquivo").name.strip() or "arquivo"
    suffix = Path(raw).suffix.lower()
    stem = raw[:-len(suffix)] if suffix else raw
    normalized = unicodedata.normalize("NFKD", stem)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_text)
    ascii_text = re.sub(r"_+", "_", ascii_text).strip("._-").lower()
    if not ascii_text:
        ascii_text = "documento"
    safe_suffix = re.sub(r"[^a-z0-9.]", "", suffix) or ".bin"
    return f"{ascii_text}{safe_suffix}"


def _log(message: str) -> None:
    app_log("API][UPLOAD", message)


def _public_document_select() -> str:
    # Build 4.2: listagem retorna só metadados, adaptada para SQLite ou Supabase.
    if is_postgres():
        return """
            SELECT
                documents.id,
                documents.user_id,
                documents.notebook_id,
                documents.filename,
                documents.file_type,
                documents.storage_path,
                documents.status,
                documents.file_size,
                documents.character_count AS text_char_count,
                documents.chunk_count,
                documents.created_at
            FROM documents
        """
    return """
        SELECT
            documents.id,
            documents.user_id,
            documents.notebook_id,
            documents.filename,
            documents.file_type,
            documents.storage_path,
            documents.status,
            documents.file_size,
            documents.text_char_count,
            documents.chunk_count,
            documents.created_at
        FROM documents
    """


@router.get("")
def list_documents(request: Request, notebook_id: str | None = None):
    user_id = get_current_user_id(request)
    _log(f"Listando metadados user_id={user_id} notebook_id={notebook_id}")
    query = _public_document_select() + " WHERE documents.user_id = ?"
    params: list = [user_id]
    if notebook_id:
        query += " AND documents.notebook_id = ?"
        params.append(notebook_id)
    query += " ORDER BY documents.created_at DESC"
    return fetch_all(query, params)


@router.delete("/{document_id}")
def delete_document(document_id: str, request: Request, notebook_id: str | None = None):
    user_id = get_current_user_id(request)
    _log(f"Removendo documento id={document_id} user_id={user_id} notebook_id={notebook_id}")

    if is_postgres():
        query = "SELECT id, storage_path, local_path, original_filename AS filename FROM documents WHERE id = ? AND user_id = ?"
    else:
        query = "SELECT id, storage_path, file_path AS local_path, filename FROM documents WHERE id = ? AND user_id = ?"
    params = [document_id, user_id]
    if notebook_id:
        query += " AND notebook_id = ?"
        params.append(notebook_id)

    doc = fetch_one(query, params)
    if not doc:
        _log(f"Documento já não existe ou não pertence ao usuário id={document_id}. Retornando OK idempotente.")
        return {"ok": True, "id": document_id, "deleted": False, "message": "Documento já removido."}

    storage_path = doc.get("storage_path")
    local_path = doc.get("local_path")

    if storage_path:
        delete_from_supabase_storage(storage_path)

    if local_path:
        try:
            path = Path(local_path)
            if path.exists() and path.is_file():
                path.unlink()
                _log(f"Arquivo local removido: {path}")
        except Exception as exc:
            _log(f"Não consegui remover arquivo local: {exc}")

    execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id))
    _log(f"Documento removido id={document_id}")
    return {"ok": True, "id": document_id, "filename": doc.get("filename")}


def _validate_notebook(mapped_user, mapped_notebook: str):
    notebook = fetch_one("SELECT id FROM notebooks WHERE id = ? AND user_id = ?", (mapped_notebook, mapped_user))
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook não encontrado para este usuário.")




class DirectUploadRequest(BaseModel):
    notebook_id: str
    filename: str
    file_size: int
    content_type: str | None = None


class ProcessStorageRequest(BaseModel):
    notebook_id: str
    storage_path: str
    original_filename: str
    filename: str | None = None
    file_size: int = 0
    content_type: str | None = None


def _persist_processed_local_file(
    mapped_user: str,
    mapped_notebook: str,
    *,
    local_path: Path,
    original_name: str,
    storage_path: str | None,
    file_size: int,
):
    suffix = Path(original_name or local_path.name).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"{original_name}: envie apenas PDF, DOCX ou TXT.")

    safe_name = _safe_storage_filename(original_name)
    _log(f"Processando arquivo local já recebido original={original_name!r} local={local_path} storage_path={storage_path}")

    text = read_file(local_path)
    text_len = len(text or "")
    _log(f"Caracteres extraídos: {text_len}")

    chunks = chunk_text(text, size=900, overlap=120)
    chunk_count = len(chunks)
    _log(f"Chunks gerados: {chunk_count}")

    if text.startswith("[Erro ao ler"):
        status = "error"
        chunks = [text]
        chunk_count = 1
    elif not chunks:
        status = "empty"
        chunks = ["[Nenhum texto útil foi extraído deste arquivo.]"]
        chunk_count = 1
    else:
        status = "processed"

    if is_postgres():
        doc_id = str(uuid4())
        execute(
            """
            INSERT INTO documents
            (id, user_id, notebook_id, filename, original_filename, file_type, file_size,
             storage_bucket, storage_path, local_path, status, character_count, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id, mapped_user, mapped_notebook, safe_name, original_name, suffix.replace('.', ''), file_size,
                settings.supabase_bucket, storage_path, str(local_path), status, text_len, chunk_count,
            ),
        )
        execute_many(
            """
            INSERT INTO document_chunks
            (document_id, notebook_id, user_id, content, page_number, chunk_index, character_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [(doc_id, mapped_notebook, mapped_user, chunk, 1, idx, len(chunk)) for idx, chunk in enumerate(chunks)],
        )
    else:
        doc_id = execute(
            """
            INSERT INTO documents
            (user_id, notebook_id, filename, file_type, file_path, storage_path, status, file_size, text_char_count, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (mapped_user, mapped_notebook, safe_name, suffix.replace('.', ''), str(local_path), storage_path, status, file_size, text_len, chunk_count),
            returning=True,
        )
        execute_many(
            "INSERT INTO document_chunks (document_id, notebook_id, content, page_number, chunk_index) VALUES (?, ?, ?, ?, ?)",
            [(doc_id, mapped_notebook, chunk, 1, idx) for idx, chunk in enumerate(chunks)],
        )

    _log(f"Documento persistido id={doc_id} status={status} chunks={chunk_count}")
    return {
        "id": doc_id,
        "filename": safe_name,
        "original_filename": original_name,
        "file_type": suffix.replace('.', ''),
        "file_size": file_size,
        "text_char_count": text_len,
        "chunk_count": chunk_count,
        "chunks": chunk_count,
        "status": status,
        "storage_path": storage_path,
    }


def _insert_processed_document(mapped_user, mapped_notebook: str, upload_file: UploadFile, content: bytes):
    suffix = Path(upload_file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        _log(f"Tipo recusado: {suffix}")
        raise HTTPException(status_code=400, detail=f"{upload_file.filename}: envie apenas PDF, DOCX ou TXT.")

    original_name = Path(upload_file.filename or "arquivo").name
    safe_name = _safe_storage_filename(original_name)

    # Build 6.3: no Supabase Storage, o path não deve carregar nome completo do arquivo,
    # porque isso pode expor dados pessoais e gerar paths enormes.
    # O nome original continua salvo no banco; o storage usa document_id.ext.
    doc_id_override = str(uuid4()) if is_postgres() else None
    storage_filename = f"{doc_id_override}{suffix}" if doc_id_override else f"{int(time())}_{safe_name}"
    local_filename = f"{int(time())}_{safe_name}"
    _log(f"Nome original={original_name!r} nome_storage={storage_filename!r} nome_exibicao={safe_name!r}")
    target = UPLOAD_DIR / local_filename

    file_size = len(content)
    _log(f"Bytes recebidos: {file_size}")
    if file_size > MAX_UPLOAD_BYTES:
        _log(f"Arquivo recusado por tamanho: {file_size} bytes")
        raise HTTPException(status_code=413, detail=f"{original_name}: arquivo muito grande. Limite atual: {MAX_UPLOAD_MB} MB.")

    target.write_bytes(content)
    _log(f"Arquivo salvo localmente em: {target}")

    text = read_file(target)
    text_len = len(text or "")
    _log(f"Caracteres extraídos: {text_len}")

    chunks = chunk_text(text, size=900, overlap=120)
    chunk_count = len(chunks)
    _log(f"Chunks gerados: {chunk_count}")

    if text.startswith("[Erro ao ler"):
        status = "error"
        chunks = [text]
        chunk_count = 1
    elif not chunks:
        status = "empty"
        chunks = ["[Nenhum texto útil foi extraído deste arquivo.]"]
        chunk_count = 1
    else:
        status = "processed"

    storage_path = upload_to_supabase_storage(target, f"users/{mapped_user}/notebooks/{mapped_notebook}/{storage_filename}")
    _log(f"Storage path: {storage_path or 'local/fallback'}")

    if is_postgres():
        doc_id = doc_id_override
        execute(
            """
            INSERT INTO documents
            (id, user_id, notebook_id, filename, original_filename, file_type, file_size,
             storage_bucket, storage_path, local_path, status, character_count, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id, mapped_user, mapped_notebook, safe_name, original_name, suffix.replace('.', ''), file_size,
                settings.supabase_bucket, storage_path, str(target), status, text_len, chunk_count,
            ),
        )
        execute_many(
            """
            INSERT INTO document_chunks
            (document_id, notebook_id, user_id, content, page_number, chunk_index, character_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [(doc_id, mapped_notebook, mapped_user, chunk, 1, idx, len(chunk)) for idx, chunk in enumerate(chunks)],
        )
    else:
        doc_id = execute(
            """
            INSERT INTO documents
            (user_id, notebook_id, filename, file_type, file_path, storage_path, status, file_size, text_char_count, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (mapped_user, mapped_notebook, safe_name, suffix.replace('.', ''), str(target), storage_path, status, file_size, text_len, chunk_count),
            returning=True,
        )
        execute_many(
            "INSERT INTO document_chunks (document_id, notebook_id, content, page_number, chunk_index) VALUES (?, ?, ?, ?, ?)",
            [(doc_id, mapped_notebook, chunk, 1, idx) for idx, chunk in enumerate(chunks)],
        )

    _log(f"Documento salvo no banco id={doc_id} status={status} chunks={chunk_count}")
    return {
        "id": doc_id,
        "filename": safe_name,
        "original_filename": original_name,
        "file_type": suffix.replace('.', ''),
        "file_size": file_size,
        "text_char_count": text_len,
        "chunk_count": chunk_count,
        "chunks": chunk_count,
        "status": status,
        "storage_path": storage_path,
    }




@router.post("/direct-upload-url")
def create_direct_upload_url(payload: DirectUploadRequest, request: Request):
    """Cria uma URL assinada para o navegador enviar arquivo direto ao Supabase Storage.

    Usado na Vercel para evitar 413 FUNCTION_PAYLOAD_TOO_LARGE.
    """
    mapped_user = get_current_user_id(request)
    mapped_notebook = payload.notebook_id
    _validate_notebook(mapped_user, mapped_notebook)

    suffix = Path(payload.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"{payload.filename}: envie apenas PDF, DOCX ou TXT.")
    if payload.file_size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{payload.filename}: arquivo muito grande. Limite atual: {MAX_UPLOAD_MB} MB.")

    doc_id = str(uuid4())
    storage_filename = f"{doc_id}{suffix}"
    storage_path = f"users/{mapped_user}/notebooks/{mapped_notebook}/{storage_filename}"
    try:
        signed = create_signed_upload_url(storage_path)
    except Exception as exc:
        _log(f"Falha ao criar signed upload URL: {exc}")
        raise HTTPException(status_code=500, detail=f"Falha ao preparar upload direto: {exc}")

    return {
        "ok": True,
        "mode": "direct_storage_upload",
        "storage_path": signed["storage_path"],
        "signed_url": signed["signed_url"],
        "token": signed.get("token"),
        "bucket": settings.supabase_bucket,
        "max_upload_mb": MAX_UPLOAD_MB,
    }


@router.post("/process-storage")
def process_storage_document(payload: ProcessStorageRequest, request: Request):
    """Processa um arquivo que já foi enviado diretamente ao Supabase Storage."""
    mapped_user = get_current_user_id(request)
    mapped_notebook = payload.notebook_id
    _validate_notebook(mapped_user, mapped_notebook)

    storage_path = (payload.storage_path or "").replace("\\", "/").strip("/")
    expected_prefix = f"users/{mapped_user}/notebooks/{mapped_notebook}/"
    if not storage_path.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Storage path não pertence a este usuário/notebook.")

    original_name = Path(payload.original_filename or payload.filename or storage_path).name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"{original_name}: envie apenas PDF, DOCX ou TXT.")

    local_name = f"{int(time())}_{_safe_storage_filename(original_name)}"
    target = UPLOAD_DIR / local_name
    try:
        download_from_supabase_storage(storage_path, target)
        actual_size = target.stat().st_size
        if actual_size > MAX_UPLOAD_BYTES:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
            raise HTTPException(status_code=413, detail=f"{original_name}: arquivo muito grande. Limite atual: {MAX_UPLOAD_MB} MB.")
        processed = _persist_processed_local_file(
            mapped_user,
            mapped_notebook,
            local_path=target,
            original_name=original_name,
            storage_path=storage_path,
            file_size=actual_size or payload.file_size,
        )
        response = {"ok": True, "uploaded": [processed], "errors": [], "count": 1, "error_count": 0}
        response.update(processed)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        _log(f"Falha ao processar arquivo do Storage: {exc}")
        raise HTTPException(status_code=500, detail=f"Falha ao processar arquivo enviado ao Storage: {exc}")


@router.post("/upload")
async def upload_document(
    request: Request,
    notebook_id: str = Form(...),
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
):
    """Upload autenticado com suporte a múltiplos arquivos.

    O frontend da Build 6.1 envia vários arquivos no campo `files`.
    O campo `file` fica por compatibilidade com builds antigas.
    Se um arquivo falhar, os demais continuam sendo processados.
    """
    mapped_user = get_current_user_id(request)
    mapped_notebook = notebook_id
    _validate_notebook(mapped_user, mapped_notebook)

    incoming: list[UploadFile] = []
    if files:
        incoming.extend([f for f in files if f and f.filename])
    if file and file.filename and not any(f.filename == file.filename for f in incoming):
        incoming.append(file)

    if not incoming:
        raise HTTPException(status_code=400, detail="Nenhum arquivo recebido.")

    _log(f"Recebendo upload múltiplo total={len(incoming)} user_id={mapped_user} notebook_id={mapped_notebook}")
    uploaded = []
    errors = []

    for upload_file in incoming:
        try:
            _log(f"Processando arquivo filename={upload_file.filename!r}")
            content = await upload_file.read()
            uploaded.append(_insert_processed_document(mapped_user, mapped_notebook, upload_file, content))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            _log(f"ERRO no arquivo {upload_file.filename!r}: {detail}")
            errors.append({"filename": upload_file.filename, "error": detail, "status_code": exc.status_code})
        except Exception as exc:
            _log(f"ERRO inesperado no arquivo {upload_file.filename!r}: {exc}")
            errors.append({"filename": upload_file.filename, "error": str(exc), "status_code": 500})

    if not uploaded and errors:
        raise HTTPException(status_code=400, detail={"message": "Nenhum arquivo foi processado.", "errors": errors})

    # Compatibilidade: se só veio um arquivo, expõe também os campos no nível raiz.
    response = {"ok": True, "uploaded": uploaded, "errors": errors, "count": len(uploaded), "error_count": len(errors)}
    if len(uploaded) == 1:
        response.update(uploaded[0])
    return response
