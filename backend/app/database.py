import sqlite3
from pathlib import Path
from typing import Any, Iterable

from app.config import settings
from app.app_logger import info as log_info

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # psycopg só é necessário em produção com PostgreSQL/Supabase
    psycopg = None
    dict_row = None

BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_PATH = BASE_DIR / "studyflow.db"
DEFAULT_SUPABASE_USER_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_SUPABASE_NOTEBOOK_ID = "00000000-0000-0000-0000-000000000101"


def is_postgres() -> bool:
    return settings.database_url.startswith(("postgres://", "postgresql://"))


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def map_user_id(value):
    if is_postgres() and (value in (None, "", 1, "1")):
        return DEFAULT_SUPABASE_USER_ID
    return int(value) if not is_postgres() and str(value).isdigit() else value


def map_notebook_id(value):
    if is_postgres() and (value in (None, "", 1, "1")):
        return DEFAULT_SUPABASE_NOTEBOOK_ID
    return int(value) if not is_postgres() and str(value).isdigit() else value


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notebooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    notebook_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    storage_path TEXT,
    status TEXT DEFAULT 'processed',
    file_size INTEGER DEFAULT 0,
    text_char_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    notebook_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    page_number INTEGER DEFAULT 1,
    chunk_index INTEGER NOT NULL,
    embedding TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS generated_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_id INTEGER NOT NULL,
    document_id INTEGER,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    notebook_id INTEGER NOT NULL,
    document_ids TEXT DEFAULT '[]',
    title TEXT DEFAULT 'Questionário',
    score INTEGER NOT NULL DEFAULT 0,
    total_questions INTEGER NOT NULL DEFAULT 0,
    answered INTEGER NOT NULL DEFAULT 0,
    answers TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    memory_key TEXT NOT NULL,
    memory_value TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS notebooks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notebook_id BIGINT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    storage_path TEXT,
    status TEXT DEFAULT 'processed',
    file_size BIGINT DEFAULT 0,
    text_char_count BIGINT DEFAULT 0,
    chunk_count BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    notebook_id BIGINT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    page_number INTEGER DEFAULT 1,
    chunk_index INTEGER NOT NULL,
    embedding TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    notebook_id BIGINT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS generated_materials (
    id BIGSERIAL PRIMARY KEY,
    notebook_id BIGINT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS agent_memory (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_key TEXT NOT NULL,
    memory_value TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


def _connect():
    if is_postgres():
        if psycopg is None:
            raise RuntimeError("psycopg não instalado. Rode: pip install -r requirements.txt")
        return psycopg.connect(normalize_database_url(settings.database_url), row_factory=dict_row)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def q(sql: str) -> str:
    return sql.replace("?", "%s") if is_postgres() else sql


def fetch_all(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(q(sql), tuple(params)).fetchall()
        return [dict(r) for r in rows]


def fetch_one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with _connect() as conn:
        row = conn.execute(q(sql), tuple(params)).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: Iterable[Any] = (), returning: bool = False):
    with _connect() as conn:
        final_sql = q(sql)
        if is_postgres() and returning and "RETURNING" not in final_sql.upper():
            final_sql += " RETURNING id"
        cur = conn.execute(final_sql, tuple(params))
        new_id = None
        if returning:
            if is_postgres():
                row = cur.fetchone()
                if row:
                    new_id = row["id"] if isinstance(row, dict) else row[0]
            else:
                new_id = int(cur.lastrowid)
        conn.commit()
        return new_id


def execute_many(sql: str, rows: list[Iterable[Any]]) -> None:
    if not rows:
        return
    with _connect() as conn:
        if is_postgres():
            with conn.cursor() as cur:
                cur.executemany(q(sql), [tuple(r) for r in rows])
        else:
            conn.executemany(sql, [tuple(r) for r in rows])
        conn.commit()



def _ensure_document_metadata_columns() -> None:
    """Garante colunas usadas pelo app mesmo em bancos Supabase criados por schemas antigos.

    O Render/Supabase novo pode estar com um schema parcial. Esta rotina é idempotente
    e corrige diferenças comuns sem apagar dados.
    """
    with _connect() as conn:
        if is_postgres():
            statements = [
                "ALTER TABLE profiles ALTER COLUMN password_hash DROP NOT NULL",
                "ALTER TABLE profiles ALTER COLUMN password_hash SET DEFAULT 'local-test-user-disabled'",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_filename TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_bucket TEXT DEFAULT 'documents'",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_path TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS local_path TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS character_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS mime_type TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ",
                "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES profiles(id) ON DELETE CASCADE",
                "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page_number INTEGER DEFAULT 1",
                "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS character_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
                "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS token_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
                "ALTER TABLE generated_materials ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES profiles(id) ON DELETE CASCADE",
                "ALTER TABLE generated_materials ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
                "ALTER TABLE generated_materials ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
                "ALTER TABLE agent_memory ADD COLUMN IF NOT EXISTS notebook_id UUID REFERENCES notebooks(id) ON DELETE CASCADE",
                "ALTER TABLE agent_memory ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
            ]
            for sql in statements:
                try:
                    conn.execute(sql)
                except Exception as exc:
                    log_info("DB", f"Aviso ao ajustar schema: {exc}")
            try:
                conn.execute("UPDATE documents SET original_filename = COALESCE(original_filename, filename) WHERE original_filename IS NULL")
            except Exception as exc:
                log_info("DB", f"Aviso ao preencher original_filename: {exc}")
            # Recria constraints que podem estar restritivas em schemas antigos.
            try:
                conn.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check")
                conn.execute("ALTER TABLE documents ADD CONSTRAINT documents_status_check CHECK (status in ('processing', 'processed', 'failed', 'empty', 'error'))")
            except Exception as exc:
                log_info("DB", f"Aviso ao ajustar documents_status_check: {exc}")
            try:
                conn.execute("ALTER TABLE generated_materials DROP CONSTRAINT IF EXISTS generated_materials_type_check")
                conn.execute("ALTER TABLE generated_materials ADD CONSTRAINT generated_materials_type_check CHECK (type in ('summary','quiz','study_plan','flowchart','flashcards','quick_review','compare','comparison','explain_simple','free_answer'))")
            except Exception as exc:
                log_info("DB", f"Aviso ao ajustar generated_materials_type_check: {exc}")
        else:
            columns = {
                "file_size": "INTEGER DEFAULT 0",
                "text_char_count": "INTEGER DEFAULT 0",
                "chunk_count": "INTEGER DEFAULT 0",
            }
            existing_rows = conn.execute("PRAGMA table_info(documents)").fetchall()
            existing = {r["name"] if isinstance(r, sqlite3.Row) else r[1] for r in existing_rows}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
        conn.commit()


def _ensure_quiz_attempts_table() -> None:
    """Tabela leve para registrar pontuação dos quizzes interativos."""
    if is_postgres():
        execute("""
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
                document_ids TEXT DEFAULT '[]',
                title TEXT DEFAULT 'Questionário',
                score INTEGER NOT NULL DEFAULT 0,
                total_questions INTEGER NOT NULL DEFAULT 0,
                answered INTEGER NOT NULL DEFAULT 0,
                answers TEXT DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    else:
        execute("""
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notebook_id INTEGER NOT NULL,
                document_ids TEXT DEFAULT '[]',
                title TEXT DEFAULT 'Questionário',
                score INTEGER NOT NULL DEFAULT 0,
                total_questions INTEGER NOT NULL DEFAULT 0,
                answered INTEGER NOT NULL DEFAULT 0,
                answers TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

def init_db() -> None:
    if is_postgres():
        log_info("DB", "PostgreSQL/Supabase detectado. Usando schema existente do Supabase.")
        _ensure_document_metadata_columns()
        # Garante usuário/notebook padrão para modo desenvolvimento.
        execute(
            """
            INSERT INTO profiles (id, name, email, password_hash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (email) DO NOTHING
            """,
            (DEFAULT_SUPABASE_USER_ID, "Usuário Teste", "teste@studyflow.local", "local-test-user-disabled"),
        )
        execute(
            """
            INSERT INTO notebooks (id, user_id, title, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (DEFAULT_SUPABASE_NOTEBOOK_ID, DEFAULT_SUPABASE_USER_ID, "Notebook Principal", "Notebook padrão criado para testes locais."),
        )
        _ensure_quiz_attempts_table()
        return

    with _connect() as conn:
        conn.executescript(SQLITE_SCHEMA)
        conn.commit()

    _ensure_document_metadata_columns()
    _ensure_quiz_attempts_table()

    # Usuário de demonstração para o sistema abrir sem cadastro durante testes.
    existing = fetch_one("SELECT id FROM users WHERE id = ?", (1,))
    if not existing:
        execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Kevin", "demo@studyflow.local", "demo"),
        )
    has_notebook = fetch_one("SELECT id FROM notebooks WHERE user_id = ? LIMIT 1", (1,))
    if not has_notebook:
        execute("INSERT INTO notebooks (user_id, title) VALUES (?, ?)", (1, "Aprendizado Profundo"))


def health_database() -> dict:
    try:
        if is_postgres():
            row = fetch_one("SELECT count(*) AS total FROM profiles")
            return {"ok": True, "engine": "postgres/supabase", "profiles": row.get("total", 0) if row else 0}
        row = fetch_one("SELECT count(*) AS total FROM users")
        return {"ok": True, "engine": "sqlite", "users": row.get("total", 0) if row else 0}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "engine": "postgres/supabase" if is_postgres() else "sqlite"}
