# Deploy na Vercel — Build 11 Demo

Esta versão adapta o StudyFlow PDF AI para teste/demo na Vercel.

## Importante

A Vercel usa funções serverless. Por isso, esta build é recomendada para demonstração com PDFs pequenos. Para evitar erro de limite de payload, configure:

```env
MAX_UPLOAD_SIZE_MB=4
```

PDFs grandes, como arquivos de 9 MB ou mais, podem falhar no upload/processamento na Vercel. Para produção completa com PDFs grandes, use VPS/FastAPI persistente.

## Configurações no Vercel

Framework Preset:

```txt
Other
```

Build Command:

```txt
vazio / deixar padrão
```

Output Directory:

```txt
vazio
```

Install Command:

```bash
python -m pip install -r requirements.txt
```

## Variáveis de ambiente

Configure no painel da Vercel:

```env
APP_ENV=production
APP_DEBUG=false
LOG_LEVEL=error
PYTHON_VERSION=3.12.8

DATABASE_URL=...
JWT_SECRET=...

SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
SUPABASE_ANON_KEY=...
SUPABASE_BUCKET=documents

LLM_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile

MAX_UPLOAD_SIZE_MB=4
OCR_MAX_PAGES=20
OCR_LANGUAGES=por+eng
OCR_RENDER_SCALE=2.0
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

## Health checks

Depois do deploy:

```txt
/api/health/env-check
/api/health/runtime-check
/api/health/llm/test
/api/health/deploy
```

## Teste recomendado

1. Criar usuário novo.
2. Enviar PDF pequeno, abaixo de 4 MB.
3. Pedir resumo.
4. Pedir questionário.
5. Corrigir quiz.
6. Testar histórico com logout/login.

