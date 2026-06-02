from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.database import execute, fetch_one, is_postgres

router = APIRouter()

class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))


def hash_password(password: str) -> str:
    """Hash com PBKDF2. Suporta segurança real sem depender de pacote extra."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 160_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    if stored.startswith('pbkdf2_sha256$'):
        try:
            _, salt, expected = stored.split('$', 2)
            digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 160_000).hex()
            return hmac.compare_digest(digest, expected)
        except Exception:
            return False
    # Compatibilidade com builds antigas que usavam SHA-256 puro.
    return hmac.compare_digest(hashlib.sha256(password.encode('utf-8')).hexdigest(), stored)


def create_token(user: dict[str, Any]) -> str:
    now = int(time.time())
    payload = {
        'sub': str(user['id']),
        'name': user.get('name') or 'Usuário',
        'email': user.get('email') or '',
        'iat': now,
        'exp': now + int(settings.access_token_expire_minutes) * 60,
    }
    payload_b64 = _b64(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
    secret = (settings.jwt_secret or 'change_me_in_production').encode('utf-8')
    signature = hmac.new(secret, payload_b64.encode('utf-8'), hashlib.sha256).digest()
    return f"sf.{payload_b64}.{_b64(signature)}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        prefix, payload_b64, signature_b64 = token.split('.', 2)
        if prefix != 'sf':
            raise ValueError('prefixo inválido')
        secret = (settings.jwt_secret or 'change_me_in_production').encode('utf-8')
        expected = _b64(hmac.new(secret, payload_b64.encode('utf-8'), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature_b64):
            raise ValueError('assinatura inválida')
        payload = json.loads(_unb64(payload_b64).decode('utf-8'))
        if int(payload.get('exp', 0)) < int(time.time()):
            raise ValueError('token expirado')
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f'Sessão inválida: {exc}')


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get('authorization') or request.headers.get('Authorization') or ''
    if auth.lower().startswith('bearer '):
        return auth.split(' ', 1)[1].strip()
    raise HTTPException(status_code=401, detail='Token de autenticação ausente.')


def get_current_user(request: Request) -> dict[str, Any]:
    payload = decode_token(_extract_bearer(request))
    user_id = str(payload['sub'])
    if is_postgres():
        user = fetch_one('SELECT id, name, email, created_at FROM profiles WHERE id = ?', (user_id,))
    else:
        user = fetch_one('SELECT id, name, email, created_at FROM users WHERE id = ?', (user_id,))
    if not user:
        raise HTTPException(status_code=401, detail='Usuário da sessão não existe mais.')
    return user


def get_current_user_id(request: Request):
    return get_current_user(request)['id']


def _find_user_by_email(email: str) -> dict | None:
    if is_postgres():
        return fetch_one('SELECT id, name, email, password_hash, created_at FROM profiles WHERE lower(email) = lower(?)', (email,))
    return fetch_one('SELECT id, name, email, password_hash, created_at FROM users WHERE lower(email) = lower(?)', (email,))


def _ensure_default_notebook(user_id) -> str | int:
    existing = fetch_one('SELECT id FROM notebooks WHERE user_id = ? ORDER BY created_at ASC LIMIT 1', (user_id,))
    if existing:
        return existing['id']
    if is_postgres():
        return execute(
            'INSERT INTO notebooks (user_id, title, description) VALUES (?, ?, ?)',
            (user_id, 'Meu primeiro notebook', 'Notebook criado automaticamente no cadastro.'),
            returning=True,
        )
    return execute('INSERT INTO notebooks (user_id, title) VALUES (?, ?)', (user_id, 'Meu primeiro notebook'), returning=True)


@router.post('/register')
def register(data: RegisterIn):
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail='A senha precisa ter pelo menos 6 caracteres.')
    email = data.email.lower().strip()
    if _find_user_by_email(email):
        raise HTTPException(status_code=400, detail='E-mail já cadastrado.')
    name = data.name.strip() or 'Usuário'
    password_hash = hash_password(data.password)
    if is_postgres():
        user_id = execute(
            'INSERT INTO profiles (name, email, password_hash) VALUES (?, ?, ?)',
            (name, email, password_hash),
            returning=True,
        )
        user = fetch_one('SELECT id, name, email, created_at FROM profiles WHERE id = ?', (user_id,))
    else:
        user_id = execute(
            'INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
            (name, email, password_hash),
            returning=True,
        )
        user = fetch_one('SELECT id, name, email, created_at FROM users WHERE id = ?', (user_id,))
    notebook_id = _ensure_default_notebook(user_id)
    return {'token': create_token(user), 'user': user, 'default_notebook_id': notebook_id}


@router.post('/login')
def login(data: LoginIn):
    user = _find_user_by_email(data.email.lower().strip())
    if not user or not verify_password(data.password, user.get('password_hash')):
        raise HTTPException(status_code=401, detail='E-mail ou senha inválidos.')
    notebook_id = _ensure_default_notebook(user['id'])
    safe_user = {k: user[k] for k in ('id', 'name', 'email') if k in user}
    return {'token': create_token(user), 'user': safe_user, 'default_notebook_id': notebook_id}


@router.get('/me')
def me(request: Request):
    user = get_current_user(request)
    notebook_id = _ensure_default_notebook(user['id'])
    return {'user': user, 'default_notebook_id': notebook_id}


@router.post('/logout')
def logout():
    # Stateless token: o frontend apaga o token. Futuramente pode virar blacklist/refresh token.
    return {'ok': True}
