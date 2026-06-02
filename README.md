# StudyFlow PDF AI

StudyFlow PDF AI é uma aplicação web para estudo assistido por Inteligência Artificial. O usuário pode criar uma conta, enviar PDFs, selecionar documentos como fontes e pedir ao agente materiais de estudo baseados no conteúdo real dos arquivos.

O projeto foi desenvolvido para a disciplina **Engenharia de Prompt e Aplicação em IA**, seguindo a proposta de construir uma aplicação web moderna com integração de agentes de IA, RAG, streaming, memória de sessão, autenticação e interface responsiva.

## Objetivo

Ajudar estudantes a transformar documentos em materiais de estudo úteis, como:

- resumos;
- questionários interativos;
- planos de estudo;
- fluxogramas;
- flashcards;
- revisões rápidas;
- comparações entre PDFs.

O StudyFlow não foi projetado para ser apenas um chatbot. O agente usa os documentos enviados como base e evita responder quando não há informação suficiente nas fontes selecionadas.

## Funcionalidades principais

- Cadastro e login de usuários.
- Sessão persistente com JWT.
- Isolamento de dados por usuário.
- Notebooks individuais.
- Upload múltiplo de PDFs.
- Armazenamento dos arquivos no Supabase Storage.
- Metadados e chunks no Supabase PostgreSQL.
- Seleção explícita de fontes.
- Agente com RAG para recuperar trechos dos PDFs.
- Streaming de respostas da IA.
- Histórico de conversa por usuário e notebook.
- Quiz interativo com correção automática.
- Salvamento de tentativas de quiz no banco.
- Fluxogramas renderizados com Mermaid.
- Interface responsiva para desktop, tablet e mobile.

## Como o agente funciona

```txt
Mensagem do usuário
  ↓
Validação da sessão
  ↓
Verificação do notebook ativo
  ↓
Verificação dos documentos selecionados
  ↓
Recuperação de chunks relevantes
  ↓
Detecção da tarefa solicitada
  ↓
Chamada ao LLM via Groq
  ↓
Resposta em streaming
  ↓
Salvamento no histórico
```

Quando há vários documentos no notebook e nenhum está selecionado, o sistema pede que o usuário escolha as fontes antes de continuar. Isso evita misturar conteúdos por engano.

## Tecnologias utilizadas

### Backend

- Python
- FastAPI
- Uvicorn
- Supabase PostgreSQL
- Supabase Storage
- JWT
- Groq API

### Frontend

- HTML
- CSS responsivo
- JavaScript
- Mermaid.js

### IA / LLM Developer

- RAG com busca em documentos.
- Prompt engineering.
- Streaming de respostas.
- Memória persistente por notebook.
- Controle anti-alucinação.
- Geração estruturada de quiz.
- Renderização interativa de materiais.

## Arquitetura resumida

```txt
Usuário
  ↓
Frontend responsivo
  ↓
FastAPI
  ↓
JWT / Auth
  ↓
Supabase PostgreSQL
  ↓
Supabase Storage
  ↓
RAG
  ↓
Groq LLM
  ↓
Resposta em streaming
```

## Estrutura do projeto

```txt
studyflow-pdf-ai/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── auth.py
│   │   ├── database.py
│   │   ├── documents.py
│   │   ├── storage.py
│   │   ├── chat.py
│   │   ├── agent.py
│   │   ├── rag.py
│   │   ├── llm_client.py
│   │   ├── file_reader.py
│   │   └── config.py
│   │
│   ├── static/
│   │   ├── css/
│   │   └── js/
│   │
│   ├── templates/
│   ├── uploads/
│   ├── requirements.txt
│   └── .env.example
│
├── database/
│   ├── schema.sql
│   └── schema_supabase.sql
│
├── docs/
│   ├── ARQUITETURA.md
│   ├── DOCUMENTACAO_TECNICA.md
│   ├── DEPLOY_RAILWAY.md
│   └── VARIAVEIS_AMBIENTE.md
│
├── Procfile
├── railway.json
├── nixpacks.toml
├── runtime.txt
├── README.md
└── .gitignore
```

## Rodando localmente

Entre na pasta do backend:

```powershell
cd backend
```

Crie o ambiente virtual:

```powershell
py -3.12 -m venv .venv
```

Ative o ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
pip install -r requirements.txt
```

Crie o arquivo `.env` a partir do exemplo:

```powershell
copy .env.example .env
```

Execute o servidor:

```powershell
uvicorn app.main:app --reload
```

Abra:

```txt
http://127.0.0.1:8000
```

## Variáveis de ambiente

As variáveis necessárias estão documentadas em:

```txt
docs/VARIAVEIS_AMBIENTE.md
```

Nunca suba `.env` para o GitHub.

## Health checks

Com o servidor rodando, acesse:

```txt
/api/health/database
/api/health/storage
/api/health/llm
/api/health/llm/test
/api/health/deploy
```

## Exemplos de uso

### Resumo

```txt
Faça um resumo do documento selecionado.
```

### Quiz interativo

```txt
Faça um questionário sobre esse PDF.
```

### Quiz com gabarito

```txt
Faça um questionário com gabarito.
```

### Fluxograma

```txt
Crie um fluxograma sobre o conteúdo.
```

### Plano de estudo

```txt
Monte um plano de estudo com base no PDF.
```

### Comparação

```txt
Compare os documentos selecionados.
```

## Deploy

O projeto está preparado para Railway.

Comando de start:

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Documentação completa:

```txt
docs/DEPLOY_RAILWAY.md
```

## Segurança

- Chaves de API ficam somente no backend.
- `.env` é ignorado pelo Git.
- Usuários são isolados por `user_id`.
- Documentos são separados por usuário e notebook.
- O storage usa UUID no caminho do arquivo.
- Logs mascaram dados sensíveis.
- O agente evita responder fora das fontes selecionadas.

## Status da entrega

O projeto atende aos principais requisitos da proposta:

- interface responsiva;
- autenticação com sessão persistente;
- navegação multi-tela;
- feedback visual em tempo real;
- streaming de IA;
- integração com LLM via API;
- RAG com documentos;
- histórico persistente;
- documentação técnica;
- deploy preparado.


## Diagnóstico de ambiente

A Build 10 inclui rotas específicas para evitar problemas de configuração de `.env` no deploy:

```txt
/api/health/env-check
/api/health/runtime-check
/api/health/deploy
/api/health/database
/api/health/storage
/api/health/llm
/api/health/llm/test
```

Use `/api/health/env-check` para descobrir variáveis ausentes ou mal configuradas sem expor chaves reais. Use `/api/health/runtime-check` para validar banco, Storage, LLM e tabelas principais.

Veja também: `docs/VALIDACAO_AMBIENTE.md`.
