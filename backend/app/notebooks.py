from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.database import execute, fetch_all, fetch_one, is_postgres

router = APIRouter()

class NotebookIn(BaseModel):
    title: str = "Novo notebook"


def _normalize_title(title: str) -> str:
    title = (title or "Novo notebook").strip()
    return title[:80] or "Novo notebook"


@router.get("")
def list_notebooks(request: Request):
    user_id = get_current_user_id(request)
    return fetch_all("SELECT * FROM notebooks WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC", (user_id,))


@router.post("")
def create_notebook(data: NotebookIn, request: Request):
    user_id = get_current_user_id(request)
    title = _normalize_title(data.title)
    if is_postgres():
        notebook_id = execute(
            "INSERT INTO notebooks (user_id, title, description) VALUES (?, ?, ?)",
            (user_id, title, "Notebook criado pelo usuário."),
            returning=True,
        )
    else:
        notebook_id = execute(
            "INSERT INTO notebooks (user_id, title) VALUES (?, ?)",
            (user_id, title),
            returning=True,
        )
    return {"id": notebook_id, "title": title}


@router.delete("/{notebook_id}")
def delete_notebook(notebook_id: str, request: Request):
    user_id = get_current_user_id(request)
    nb = fetch_one("SELECT id FROM notebooks WHERE id = ? AND user_id = ?", (notebook_id, user_id))
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook não encontrado para este usuário.")
    execute("DELETE FROM notebooks WHERE id = ? AND user_id = ?", (notebook_id, user_id))
    return {"ok": True, "id": notebook_id}
