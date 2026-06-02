# Documentação Técnica — StudyFlow PDF AI

## 1. Visão geral

O StudyFlow PDF AI é uma aplicação web de estudo assistido por IA. O usuário envia documentos, seleciona fontes e interage com um agente que gera materiais de estudo com base no conteúdo recuperado dos PDFs.

A proposta do sistema é ir além de um chatbot comum: a IA participa do fluxo principal da aplicação, usa documentos como fonte, mantém histórico e gera materiais interativos.

## 2. Problema resolvido

Estudantes normalmente acumulam PDFs longos e pouco organizados. O StudyFlow ajuda a transformar esses arquivos em materiais mais fáceis de estudar:

- resumo;
- questionário;
- plano de estudo;
- fluxograma;
- flashcards;
- revisão rápida;
- comparação entre documentos.

## 3. Arquitetura

```txt
Frontend responsivo
  ↓
FastAPI Backend
  ↓
Autenticação JWT
  ↓
Supabase PostgreSQL
  ↓
Supabase Storage
  ↓
RAG / Recuperação de chunks
  ↓
Groq LLM
  ↓
Resposta em streaming
```

## 4. Frontend

O frontend usa HTML, CSS e JavaScript, com interface escura e responsiva.

Telas principais:

- Landing page
- Login
- Cadastro
- Dashboard
- Notebook
- Histórico
- Configurações

No notebook, o usuário encontra:

- chat com agente;
- lista de PDFs;
- seleção de fontes;
- ações rápidas;
- quiz interativo;
- renderização de Mermaid;
- menu mobile inferior.

## 5. Backend

O backend usa FastAPI.

Arquivos principais:

- `main.py`: inicialização da aplicação e health checks.
- `auth.py`: cadastro, login, logout e sessão JWT.
- `database.py`: conexão e inicialização do banco.
- `documents.py`: upload, listagem e exclusão de documentos.
- `storage.py`: integração com Supabase Storage.
- `chat.py`: streaming e histórico.
- `agent.py`: orquestração do agente.
- `rag.py`: recuperação de contexto.
- `llm_client.py`: conexão com o provider LLM.
- `file_reader.py`: extração de texto dos arquivos.
- `config.py`: variáveis de ambiente.

## 6. Banco de dados

Tabelas principais:

### `profiles`

Armazena usuários cadastrados.

### `notebooks`

Armazena notebooks pertencentes a cada usuário.

### `documents`

Armazena metadados dos arquivos enviados.

### `document_chunks`

Armazena trechos textuais extraídos dos documentos.

### `chat_messages`

Armazena histórico de mensagens por usuário e notebook.

### `generated_materials`

Armazena materiais gerados pelo agente.

### `quiz_attempts`

Armazena tentativas de quiz, pontuação e respostas escolhidas.

## 7. Upload de documentos

Fluxo de upload:

1. Usuário escolhe um ou mais PDFs.
2. Frontend envia os arquivos com token JWT.
3. Backend valida o usuário.
4. Texto é extraído.
5. Conteúdo é dividido em chunks.
6. Arquivo é enviado ao Supabase Storage.
7. Metadados são salvos em `documents`.
8. Chunks são salvos em `document_chunks`.

O storage path usa UUID para evitar expor nomes completos ou dados pessoais:

```txt
users/{user_id}/notebooks/{notebook_id}/{document_id}.pdf
```

## 8. Agente de IA

O agente segue um fluxo controlado:

1. Recebe a mensagem.
2. Detecta a tarefa solicitada.
3. Verifica documentos selecionados.
4. Recupera chunks relevantes.
5. Monta o prompt.
6. Chama o LLM.
7. Retorna a resposta em streaming.
8. Salva histórico e materiais.

Tarefas suportadas:

- resumo;
- questionário;
- plano de estudo;
- fluxograma;
- flashcards;
- revisão rápida;
- explicação simples;
- comparação de documentos;
- pergunta livre baseada nos documentos.

## 9. RAG

O sistema usa Retrieval-Augmented Generation. O PDF não é enviado inteiro ao modelo. O backend recupera trechos relevantes e envia apenas o contexto necessário.

Benefícios:

- menor custo de contexto;
- resposta mais controlada;
- menor risco de alucinação;
- uso direto dos documentos do usuário.

## 10. Prompt engineering

Os prompts orientam o agente a:

- responder apenas com base nos documentos;
- informar quando não houver base suficiente;
- evitar conhecimento externo como fonte principal;
- não mostrar gabarito antes da correção;
- gerar quiz sem repetição;
- criar Mermaid válido;
- adaptar a resposta ao tipo de tarefa.

## 11. Quiz interativo

O quiz é gerado como estrutura JSON e renderizado como formulário no frontend.

Funcionalidades:

- alternativas A/B/C/D;
- respostas ocultas antes da correção;
- botão Corrigir;
- botão Ver gabarito;
- botão Refazer;
- destaque da alternativa selecionada;
- pontuação final;
- explicação após correção;
- salvamento em `quiz_attempts`.

Se o documento for pequeno, o sistema pode gerar menos perguntas para evitar repetição ou invenção.

## 12. Histórico e memória

O histórico é persistente por usuário e notebook. Após logout/login ou F5, as mensagens antigas são carregadas novamente.

## 13. Responsividade

A aplicação possui layout adaptativo:

- desktop com layout completo;
- tablet com layout ajustado;
- mobile com menu inferior;
- painéis de PDFs e ações em gaveta;
- input fixo no chat;
- quiz adaptado para celular;
- fluxogramas com rolagem horizontal.

## 14. Segurança

Medidas adotadas:

- JWT para sessão;
- `.env` fora do repositório;
- service keys apenas no backend;
- documentos filtrados por `user_id`;
- notebooks filtrados por usuário;
- storage separado por usuário/notebook;
- logs com máscara para dados sensíveis;
- controle anti-alucinação no agente.

## 15. Desafios enfrentados

Durante o desenvolvimento, foram corrigidos problemas como:

- upload duplicado após F5;
- perda de seleção de PDFs;
- nomes inválidos no Supabase Storage;
- exposição de dados no storage path;
- histórico não carregando após login;
- quiz exibindo JSON cru;
- gabarito aparecendo cedo demais;
- layout mobile com blur;
- envio acidental de `undefined`;
- scroll horizontal no dashboard mobile.

## 16. Decisões técnicas

- FastAPI foi escolhido por simplicidade no backend.
- Supabase foi escolhido para banco e storage integrados.
- Groq foi usado como provider LLM por velocidade.
- RAG foi escolhido como técnica principal de LLM Developer.
- JWT foi usado para manter sessão persistente.
- Mermaid foi usado para fluxogramas.
- O quiz interativo foi renderizado no frontend para tornar a experiência mais rica que uma resposta textual.
