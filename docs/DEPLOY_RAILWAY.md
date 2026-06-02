# Deploy no Railway

## 1. Preparar o repositório

Antes de subir para o GitHub, confira:

```bash
git status
```

Não deve aparecer:

```txt
.env
backend/.env
.venv
backend/.venv
*.db
backend/uploads/arquivos reais
__pycache__
*.pyc
```

## 2. Configurar variáveis de ambiente

No Railway, configure:

```env
APP_ENV=production
APP_DEBUG=false
LOG_LEVEL=error

DATABASE_URL=

JWT_SECRET=
ACCESS_TOKEN_EXPIRE_MINUTES=1440

SUPABASE_URL=
SUPABASE_SERVICE_KEY=
SUPABASE_ANON_KEY=
SUPABASE_BUCKET=documents

LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

MAX_UPLOAD_SIZE_MB=15
OCR_MAX_PAGES=50
OCR_LANGUAGES=por+eng
OCR_RENDER_SCALE=2.2
```

## 3. Start command

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

O arquivo `railway.json` já contém esse comando.

## 4. Banco de dados

Use o Supabase PostgreSQL. O schema principal está em:

```txt
database/schema_supabase.sql
```

## 5. Storage

Crie um bucket no Supabase Storage chamado:

```txt
documents
```

## 6. Health checks pós-deploy

Após o Railway gerar a URL pública, teste:

```txt
/api/health/env-check
/api/health/runtime-check
/api/health/deploy
/api/health/database
/api/health/storage
/api/health/llm
/api/health/llm/test
```

## 7. Fluxo de validação manual

Após o deploy:

1. Criar usuário.
2. Fazer login.
3. Enviar PDF.
4. Selecionar fonte.
5. Pedir resumo.
6. Pedir questionário.
7. Corrigir quiz.
8. Fazer logout.
9. Entrar novamente.
10. Verificar histórico.
