# Variáveis de Ambiente

Nunca suba valores reais para o GitHub.

## Aplicação

```env
APP_ENV=development
APP_DEBUG=true
LOG_LEVEL=debug
```

Em produção:

```env
APP_ENV=production
APP_DEBUG=false
LOG_LEVEL=error
```

## Autenticação

```env
JWT_SECRET=
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

`JWT_SECRET` deve ser uma chave longa e aleatória.

## Banco de dados

SQLite local:

```env
DATABASE_URL=sqlite:///./data/studyflow.db
```

Supabase/PostgreSQL:

```env
DATABASE_URL=postgresql://USUARIO:SENHA@HOST:PORTA/postgres
```

## Supabase

```env
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
SUPABASE_ANON_KEY=
SUPABASE_BUCKET=documents
```

A `SUPABASE_SERVICE_KEY` deve ficar apenas no backend.

## LLM

Groq:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
```

Providers opcionais:

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
```

## Upload e OCR

```env
MAX_UPLOAD_SIZE_MB=15
OCR_MAX_PAGES=50
OCR_LANGUAGES=por+eng
OCR_RENDER_SCALE=2.2
```


## Build 10: validação automática

Use `/api/health/env-check` para validar as variáveis configuradas sem revelar chaves reais. Use `/api/health/runtime-check` para validar serviços externos e tabelas principais.
