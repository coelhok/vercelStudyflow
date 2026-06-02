# Validação de ambiente — Build 10

A Build 10 adiciona rotas para diagnosticar problemas de `.env` e de deploy sem expor chaves reais.

## Rotas de diagnóstico

Depois de rodar o sistema, acesse:

```txt
/api/health/env-check
/api/health/runtime-check
/api/health/deploy
/api/health/database
/api/health/storage
/api/health/llm
/api/health/llm/test
```

## O que cada rota faz

### `/api/health/env-check`

Valida se as variáveis principais existem e parecem corretas:

- `DATABASE_URL`
- `JWT_SECRET`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `SUPABASE_ANON_KEY`
- `SUPABASE_BUCKET`
- `LLM_PROVIDER`
- `GROQ_API_KEY`
- configurações de upload/OCR

A rota mostra apenas metadados, tamanho e preview mascarado. Ela não mostra a chave real.

### `/api/health/runtime-check`

Testa serviços externos e tabelas principais:

- banco conectado
- Supabase Storage conectado
- provider LLM configurado
- tabelas principais existentes
- `quiz_attempts` existente

### `/api/health/llm/test`

Faz uma chamada real curta ao provider de IA configurado. O esperado é receber `OK`.

## Ambiente local recomendado

```env
APP_ENV=development
APP_DEBUG=true
LOG_LEVEL=debug
```

## Ambiente Railway recomendado

```env
APP_ENV=production
APP_DEBUG=false
LOG_LEVEL=error
```

## Variáveis obrigatórias no Railway

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

MAX_UPLOAD_SIZE_MB=15
OCR_MAX_PAGES=50
OCR_LANGUAGES=por+eng
OCR_RENDER_SCALE=2.2
```

## Erros comuns

### `DATABASE_URL` usando SQLite em produção

No Railway use PostgreSQL/Supabase, não SQLite.

### `SUPABASE_BUCKET` não encontrado

Crie o bucket `documents` no Supabase Storage ou ajuste a variável para o nome correto.

### Groq não responde

Verifique:

- `LLM_PROVIDER=groq`
- `GROQ_API_KEY` começa com `gsk_`
- `GROQ_MODEL=llama-3.3-70b-versatile`

### JWT inválido ou logout constante

Gere uma chave nova:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Cole em `JWT_SECRET`.
