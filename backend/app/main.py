from pathlib import Path
import os
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import router as auth_router
from app.documents import router as documents_router
from app.chat import router as chat_router
from app.notebooks import router as notebooks_router
from app.database import init_db, health_database
from app.config import settings
from app.storage import health_storage
from app.llm_client import provider_info, call_llm
from app.env_check import env_check, runtime_check

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path("/tmp/studyflow_uploads") if os.getenv("VERCEL") else BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title=settings.app_name, version="1.1.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health")
def health():
    return {"ok": True, "service": settings.app_name, "version": "1.1.0"}

@app.get("/api/health/database")
def api_health_database():
    return health_database()

@app.get("/api/health/storage")
def api_health_storage():
    return health_storage()

@app.get("/api/health/llm")
def api_health_llm():
    info = provider_info()
    return {"ok": bool(info.get("configured")), **info}

@app.get("/api/health/deploy")
def api_health_deploy():
    """Health check consolidado para Railway/deploy."""
    db = health_database()
    storage = health_storage()
    llm = provider_info()
    env = env_check()
    ok = bool(db.get("ok")) and bool(storage.get("ok")) and bool(llm.get("configured")) and bool(env.get("ok"))
    return {
        "ok": ok,
        "service": settings.app_name,
        "version": "1.1.0",
        "environment": settings.app_env,
        "debug": settings.app_debug,
        "log_level": settings.log_level,
        "database": db,
        "storage": storage,
        "llm": llm,
        "env_check": {
            "ok": env.get("ok"),
            "summary": env.get("summary"),
            "next_steps": env.get("next_steps"),
        },
    }


@app.get("/api/health/env-check")
def api_health_env_check():
    """Valida variáveis de ambiente sem expor valores sensíveis.

    Use antes do deploy e no Railway para descobrir exatamente o que falta configurar.
    """
    return env_check()

@app.get("/api/health/runtime-check")
def api_health_runtime_check():
    """Verifica serviços externos e tabelas principais sem modificar dados.

    Complementa /api/health/env-check testando banco, storage, LLM configurado e schema.
    """
    return runtime_check()

@app.get("/api/health/llm/test")
def api_health_llm_test():
    """Executa uma chamada real curta ao provider configurado, sem usar documentos.

    Útil para diferenciar erro de chave/modelo/rede de erro do RAG.
    """
    result = call_llm(
        "Responda apenas com a palavra OK.",
        "Teste de conectividade do StudyFlow. Responda OK.",
        max_tokens=20,
    )
    return {
        "ok": result.ok,
        "provider": result.provider,
        "model": result.model,
        "chars": len(result.text or ""),
        "preview": (result.text or "")[:80],
        "error": result.error,
    }

# Páginas HTML servidas pelo próprio FastAPI. Assim o sistema inteiro roda em uma porta só.
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Evita 404 ruidoso em logs quando o navegador solicita favicon.
    return Response(status_code=204)

@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_probe():
    # Chrome DevTools solicita este arquivo em alguns ambientes. Evita 404 ruidoso.
    return Response(status_code=204)

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/dashboard")
def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/notebook")
def notebook_page(request: Request):
    return templates.TemplateResponse("notebook.html", {"request": request})

@app.get("/history")
def history_page(request: Request):
    return templates.TemplateResponse("history.html", {"request": request})

@app.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# API oficial em /api para produção/deploy.
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(notebooks_router, prefix="/api/notebooks", tags=["notebooks"])
app.include_router(documents_router, prefix="/api/documents", tags=["documents"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])

# Rotas antigas mantidas por compatibilidade com testes da Build 2.
app.include_router(auth_router, prefix="/auth", tags=["legacy-auth"])
app.include_router(notebooks_router, prefix="/notebooks", tags=["legacy-notebooks"])
app.include_router(documents_router, prefix="/documents", tags=["legacy-documents"])
app.include_router(chat_router, prefix="/chat", tags=["legacy-chat"])
