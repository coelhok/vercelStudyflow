# Arquitetura — StudyFlow PDF AI

## Visão macro

```txt
Browser
  ↓
Templates HTML + CSS + JavaScript
  ↓
FastAPI
  ↓
Módulos internos
  ↓
Supabase PostgreSQL / Storage
  ↓
Groq LLM
```

## Camadas

### 1. Interface

Responsável por exibir páginas, enviar comandos, renderizar streaming, abrir painéis mobile e mostrar materiais interativos.

Principais arquivos:

```txt
backend/templates/
backend/static/css/
backend/static/js/
```

### 2. API/BFF

Responsável por receber chamadas do frontend e orquestrar autenticação, documentos, chat e agente.

Principais arquivos:

```txt
backend/app/main.py
backend/app/auth.py
backend/app/documents.py
backend/app/chat.py
backend/app/notebooks.py
```

### 3. Dados

Responsável por persistência no PostgreSQL/Supabase.

Principais tabelas:

```txt
profiles
notebooks
documents
document_chunks
chat_messages
generated_materials
quiz_attempts
```

### 4. Storage

Responsável por armazenar os arquivos originais.

Padrão de path:

```txt
users/{user_id}/notebooks/{notebook_id}/{document_id}.pdf
```

### 5. IA

Responsável por recuperar contexto e gerar respostas.

Principais arquivos:

```txt
backend/app/agent.py
backend/app/rag.py
backend/app/llm_client.py
```

## Fluxo de chat com RAG

```txt
Usuário envia mensagem
  ↓
Frontend envia POST /api/chat/stream
  ↓
Backend valida JWT
  ↓
Backend valida notebook
  ↓
Backend limpa documentos selecionados
  ↓
RAG recupera chunks
  ↓
Agente monta prompt
  ↓
LLM gera resposta
  ↓
Streaming para o frontend
  ↓
Mensagem é salva no banco
```

## Fluxo de upload

```txt
Usuário seleciona PDFs
  ↓
Frontend envia FormData
  ↓
Backend valida usuário
  ↓
Extrai texto
  ↓
Gera chunks
  ↓
Salva arquivo no Storage
  ↓
Salva metadados no banco
  ↓
Salva chunks
  ↓
Frontend atualiza lista
```

## Fluxo de quiz

```txt
Usuário pede questionário
  ↓
Agente gera quiz estruturado
  ↓
Frontend detecta interactive_quiz
  ↓
Renderiza formulário
  ↓
Usuário escolhe alternativas
  ↓
Frontend corrige
  ↓
Resultado é salvo em quiz_attempts
```
