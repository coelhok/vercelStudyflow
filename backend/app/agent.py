from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from app.database import execute, fetch_all, is_postgres, map_notebook_id, map_user_id
from app.llm_client import call_llm, provider_info
from app.rag import build_context_for_documents, context_coverage_report, extract_query_terms, normalize
from app.app_logger import log as app_log


@dataclass
class AgentPlan:
    tasks: list[str]
    mode: str
    friendly_mode: str
    out_of_scope_risk: bool = False


TASK_LABELS = {
    "summary": "resumo",
    "quiz": "questionário",
    "flowchart": "fluxograma",
    "study_plan": "plano de estudo",
    "flashcards": "flashcards",
    "quick_review": "revisão rápida",
    "compare_docs": "comparação de documentos",
    "explain_simple": "explicação simples",
    "free_question": "resposta com base nos documentos",
}

MATERIAL_TASKS = {"summary", "quiz", "flowchart", "study_plan", "flashcards", "quick_review", "compare_docs", "explain_simple", "free_question"}

OUT_OF_SCOPE_HINTS = [
    "corinthians", "palmeiras", "flamengo", "santos", "são paulo", "sao paulo",
    "libertadores", "brasileirão", "brasileirao", "copa", "campeonato", "seleção", "selecao",
    "noticia", "notícias", "hoje", "tempo agora", "cotação", "preço", "piada",
    "fofoca", "receita", "filme", "música", "musica", "jogo de hoje", "escalação", "escalacao",
]


def _detected_out_of_scope_terms(message: str) -> list[str]:
    msg_norm = normalize(message or "")
    found: list[str] = []
    for hint in OUT_OF_SCOPE_HINTS:
        hint_norm = normalize(hint)
        if hint_norm and hint_norm in msg_norm and hint_norm not in found:
            found.append(hint_norm)
    return found


def _should_block_out_of_scope(message: str, context: str, plan: AgentPlan) -> bool:
    """Bloqueia perguntas claramente externas quando os termos não aparecem nas fontes.

    Ex.: usuário seleciona PDF de IA e pergunta escalação do Palmeiras.
    O agente não deve responder como chatbot geral; deve dizer que a informação não está nos documentos.
    """
    if plan.tasks != ["free_question"]:
        return False
    terms = _detected_out_of_scope_terms(message)
    if not terms:
        return False
    ctx_norm = normalize(context or "")
    # Se o próprio documento contiver o termo, deixamos a IA responder baseada no trecho.
    return not any(term in ctx_norm for term in terms)


def _quiz_user_requested_answers(message: str) -> bool:
    msg = normalize(message or "")
    answer_terms = [
        "com gabarito", "mostre o gabarito", "mostrar o gabarito", "com respostas",
        "mostre as respostas", "mostrar as respostas", "corrigido", "resolvido",
        "com correcao", "com correção"
    ]
    no_answer_terms = ["sem gabarito", "sem respostas", "nao mostre", "não mostre", "sem mostrar"]
    if any(term in msg for term in no_answer_terms):
        return False
    return any(term in msg for term in answer_terms)


def _quiz_mode_instruction(message: str) -> str:
    show_answers = _quiz_user_requested_answers(message)
    return (
        "MODO DO QUESTIONÁRIO:\n"
        f"- show_answers = {str(show_answers).lower()}\n"
        "- Por padrão, NÃO mostre gabarito nem respostas corretas no texto visível.\n"
        "- Só mostre gabarito/respostas se show_answers = true.\n"
        "- Gere perguntas únicas: não repita enunciado, conceito, alternativas, explicações ou respostas.\n"
        "- Se não houver conteúdo suficiente para 5 perguntas diferentes, gere menos perguntas e avise.\n"
        "- Para o frontend renderizar em estilo Forms, retorne o questionário em UM bloco ```quiz com JSON válido.\n"
        "- O JSON deve seguir exatamente este formato: {\"type\":\"interactive_quiz\",\"title\":\"...\",\"show_answers\":false,\"questions\":[{\"question\":\"...\",\"options\":{\"A\":\"...\",\"B\":\"...\",\"C\":\"...\",\"D\":\"...\"},\"correct\":\"A\",\"explanation\":\"...\"}]}\n"
        "- O campo correct deve existir para correção automática, mas o frontend só revela depois que o usuário responder, exceto quando show_answers = true.\n"
    )


def _unique_keep_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        key = normalize(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _quiz_json_block(quiz: dict) -> str:
    return "```quiz\n" + json.dumps(quiz, ensure_ascii=False, indent=2) + "\n```"


def _dedupe_quiz_questions(questions: list[dict]) -> list[dict]:
    clean: list[dict] = []
    seen_questions = set()
    seen_concepts = set()
    for q in questions:
        question = str(q.get("question") or "").strip()
        options = q.get("options") or {}
        correct = str(q.get("correct") or "A").strip().upper()[:1] or "A"
        explanation = str(q.get("explanation") or "").strip()
        q_key = normalize(question)
        concept_key = " ".join(q_key.split()[:8])
        if not question or q_key in seen_questions or concept_key in seen_concepts:
            continue
        labels = ["A", "B", "C", "D"]
        fixed_options = {label: str(options.get(label) or "").strip() for label in labels}
        if any(not fixed_options[label] for label in labels):
            continue
        # Alternativas não podem ser iguais entre si.
        if len({normalize(v) for v in fixed_options.values()}) < 4:
            continue
        if correct not in labels:
            correct = "A"
        seen_questions.add(q_key)
        seen_concepts.add(concept_key)
        clean.append({
            "question": question,
            "options": fixed_options,
            "correct": correct,
            "explanation": explanation or "Explicação baseada nos trechos recuperados do documento.",
        })
        if len(clean) >= 5:
            break
    return clean


def _normalize_interactive_quiz_blocks(text: str, show_answers: bool) -> str:
    """Garante que blocos ```quiz estejam válidos, sem perguntas repetidas.

    Se o LLM gerar um JSON bom, validamos. Se vier ruim, mantemos o texto original para não quebrar a resposta.
    """
    def repl(match: re.Match) -> str:
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
            if payload.get("type") != "interactive_quiz":
                return match.group(0)
            questions = _dedupe_quiz_questions(payload.get("questions") or [])
            payload["questions"] = questions
            payload["show_answers"] = bool(show_answers)
            payload["title"] = payload.get("title") or "Questionário interativo"
            if not questions:
                return "Não encontrei perguntas únicas suficientes para montar um questionário seguro com base nos trechos recuperados."
            note = ""
            if len(questions) < 5:
                note = f"\n\n> Consegui gerar {len(questions)} pergunta(s) sem repetição com base nos trechos recuperados."
            return _quiz_json_block(payload) + note
        except Exception:
            return match.group(0)

    return re.sub(r"```quiz\s*([\s\S]*?)```", repl, text or "", flags=re.IGNORECASE)


def _log(message: str) -> None:
    app_log("AGENT", message)


def detect_tasks(message: str) -> list[str]:
    msg = (message or "").lower()
    tasks: list[str] = []

    checks = [
        ("summary", ["resumo", "resuma", "resumir", "sintese", "síntese", "sumarize", "sumário", "principais pontos"]),
        ("quiz", ["question", "quiz", "pergunta", "questões", "questoes", "questionário", "questionario", "exercício", "exercicio", "atividade"]),
        ("flowchart", ["fluxograma", "fluxo", "mermaid", "diagrama", "mapa de fluxo", "processo visual"]),
        ("study_plan", ["plano", "cronograma", "rotina de estudo", "estudo semanal", "organize meus estudos", "plano de estudo"]),
        ("flashcards", ["flashcard", "flashcards", "cartão", "cartao"]),
        ("quick_review", ["revisão rápida", "revisao rapida", "revisar", "revisão", "revisao", "pontos principais"]),
        ("compare_docs", ["comparar", "compare", "diferença", "diferenças", "diferencas", "semelhanças", "semelhancas"]),
        ("explain_simple", ["iniciante", "simples", "explique", "explica", "fácil", "facil", "didático", "didatico", "leigo"]),
    ]

    for task, keywords in checks:
        if any(k in msg for k in keywords):
            tasks.append(task)

    if not tasks:
        tasks.append("free_question")

    unique: list[str] = []
    for task in tasks:
        if task not in unique:
            unique.append(task)
    return unique


def _recent_documents(notebook_id, user_id, limit: int = 3) -> list[dict]:
    return fetch_all(
        "SELECT * FROM documents WHERE notebook_id = ? AND user_id = ? AND status = 'processed' ORDER BY created_at DESC LIMIT ?",
        (notebook_id, user_id, limit),
    )


def _all_processed_documents(notebook_id, user_id, limit: int = 20) -> list[dict]:
    return fetch_all(
        "SELECT * FROM documents WHERE notebook_id = ? AND user_id = ? AND status = 'processed' ORDER BY created_at DESC LIMIT ?",
        (notebook_id, user_id, limit),
    )


def get_documents(notebook_id, selected_document_ids: Iterable | None = None, user_id: str | int = "1") -> list[dict]:
    notebook_id = map_notebook_id(notebook_id)
    user_id = map_user_id(user_id)
    selected = [str(x) for x in (selected_document_ids or []) if str(x).strip()]
    if selected:
        placeholders = ",".join(["?"] * len(selected))
        docs = fetch_all(
            f"""
            SELECT * FROM documents
            WHERE notebook_id = ? AND user_id = ? AND id IN ({placeholders}) AND status = 'processed'
            ORDER BY created_at DESC
            """,
            [notebook_id, user_id, *selected],
        )
        if docs:
            return docs
        _log(f"IDs selecionados não existem mais, não pertencem ao usuário ou não estão processados: {selected}.")
        return []

    # Build 7: sem seleção explícita, só usa fallback automático quando existe exatamente 1 documento.
    # Com 2+ documentos, o agente pede seleção para evitar misturar fontes sem querer.
    docs = _all_processed_documents(notebook_id, user_id, limit=4)
    if len(docs) == 1:
        _log("Nenhum checkbox marcado; usando fallback seguro porque há exatamente 1 documento no notebook.")
        return docs
    if len(docs) > 1:
        _log(f"Nenhum checkbox marcado e há {len(docs)} documentos disponíveis. Pedindo seleção explícita.")
        return []
    return []


def build_plan(message: str, docs: list[dict]) -> AgentPlan:
    tasks = detect_tasks(message)
    if len(docs) == 0:
        mode = "sem_documento"
        friendly = "aguardando fonte"
    elif len(docs) == 1:
        mode = "single_document"
        friendly = "análise individual"
    else:
        mode = "multi_document"
        friendly = "análise multi-documento"

    msg_norm = normalize(message)
    out_risk = any(normalize(h) in msg_norm for h in OUT_OF_SCOPE_HINTS)
    return AgentPlan(tasks=tasks, mode=mode, friendly_mode=friendly, out_of_scope_risk=out_risk)


def _system_prompt() -> str:
    return """Você é o Agente de IA do StudyFlow, um tutor de estudos orientado a ferramentas, RAG e fontes selecionadas.

REGRAS OBRIGATÓRIAS E PRIORITÁRIAS:
1. Responda SOMENTE com base nos trechos fornecidos em CONTEXTO DOS DOCUMENTOS.
2. Não use conhecimento externo como fonte principal, mesmo quando a resposta parecer óbvia.
3. Se a pergunta não puder ser respondida pelos trechos, diga: "Não encontrei base suficiente nos documentos selecionados para responder com segurança.".
4. Não invente autores, páginas, datas, conceitos, conclusões, exemplos ou citações.
5. Se o usuário pedir algo aleatório, atual ou fora dos documentos, recuse de forma amigável e redirecione para o estudo dos documentos.
6. Em pedidos multi-função, organize a resposta em seções separadas e execute todas as tarefas detectadas.
7. Seja amigável, direto, didático e técnico quando necessário.
8. Sempre inclua uma seção final "Fontes usadas" com os nomes dos documentos usados.
9. Para fluxograma, responda de forma limpa: gere APENAS um bloco Mermaid válido dentro de ```mermaid, seguido de uma seção "## Explicação curta" com no máximo 4 tópicos. Não crie introdução, conclusão ou um segundo título "## Fluxograma" fora do bloco visual.
10. O fluxograma deve representar o conteúdo central do documento, não o método acadêmico de escrita. Prefira etapas conceituais/práticas do tema estudado.
11. Para questionário, NÃO mostre gabarito por padrão. Gere um quiz interativo em JSON dentro de bloco ```quiz. Só mostre gabarito se o usuário pedir explicitamente. Não repita perguntas, conceitos, alternativas ou respostas.
12. Não diga que "o PDF provavelmente" fala algo: use apenas o que está no contexto.
13. Você não é um chatbot genérico. Você é um agente que analisa fontes selecionadas e executa tarefas de estudo."""


def _task_instruction(tasks: list[str], mode: str) -> str:
    lines = []
    for task in tasks:
        if task == "summary":
            lines.append("- RESUMO: gere um resumo fiel em tópicos, destacando objetivo, conceitos centrais e conclusão quando houver base nos trechos.")
        elif task == "quiz":
            lines.append("- QUESTIONÁRIO: crie um questionário interativo em bloco ```quiz com JSON válido. Não mostre gabarito no texto por padrão. Use perguntas únicas, alternativas A-D únicas e explicação curta. Não repita conceito; gere menos de 5 se não houver conteúdo suficiente.")
        elif task == "flowchart":
            lines.append("- FLUXOGRAMA: produza um único bloco ```mermaid com flowchart TD ou flowchart LR. Use 5 a 8 nós com nomes curtos extraídos dos conceitos do documento. Depois escreva ## Explicação curta com no máximo 4 tópicos. Não use introdução nem conclusão.")
        elif task == "study_plan":
            lines.append("- PLANO DE ESTUDO: monte etapas práticas de estudo baseadas nos assuntos encontrados, sem criar conteúdo fora das fontes.")
        elif task == "flashcards":
            lines.append("- FLASHCARDS: crie cartões pergunta/resposta sobre os conceitos importantes dos trechos.")
        elif task == "quick_review":
            lines.append("- REVISÃO RÁPIDA: gere revisão curta com pontos-chave e alertas do que memorizar.")
        elif task == "compare_docs":
            lines.append("- COMPARAÇÃO: compare documentos, indicando semelhanças, diferenças e pontos exclusivos somente se houver mais de uma fonte.")
        elif task == "explain_simple":
            lines.append("- EXPLICAÇÃO SIMPLES: explique como para iniciante, sem perder fidelidade aos trechos.")
        else:
            lines.append("- RESPOSTA LIVRE: responda à pergunta do usuário somente com base nos trechos recuperados.")
    if mode == "multi_document":
        lines.append("- Como há vários documentos, deixe claro quais documentos sustentam cada parte da resposta.")
    return "\n".join(lines)


def _build_user_prompt(message: str, plan: AgentPlan, docs: list[dict], context: str, coverage: dict) -> str:
    doc_lines = "\n".join(f"- {d.get('filename') or d.get('original_filename')} ({d.get('file_type', 'arquivo')})" for d in docs)
    tasks = ", ".join(TASK_LABELS.get(t, t) for t in plan.tasks)
    return f"""PEDIDO DO USUÁRIO:
{message}

MODO DE ANÁLISE:
{plan.friendly_mode}

TAREFAS DETECTADAS:
{tasks}

RISCO DE PEDIDO FORA DO DOCUMENTO:
{plan.out_of_scope_risk}

COBERTURA DO CONTEXTO RECUPERADO:
{coverage}

INSTRUÇÕES DAS TAREFAS:
{_task_instruction(plan.tasks, plan.mode)}

{_quiz_mode_instruction(message) if "quiz" in plan.tasks else ""}
DOCUMENTOS SELECIONADOS:
{doc_lines}

CONTEXTO DOS DOCUMENTOS:
{context}

Responda em português do Brasil, com seções claras. Se o contexto não sustentar uma parte pedida, diga isso explicitamente em vez de inventar."""


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or " ").strip()
    raw = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = []
    for s in raw:
        s = s.strip(" -•\t")
        if 55 <= len(s) <= 260 and not s.startswith("[Fonte:") and s not in sentences:
            sentences.append(s)
    return sentences[:18]


def _extract_context_sentences(context: str) -> list[str]:
    # Remove cabeçalhos de fonte, mas mantém o conteúdo.
    text = re.sub(r"\[Fonte:[^\]]+\]", " ", context or "")
    return _split_sentences(text)


def _fallback_summary(sentences: list[str]) -> str:
    bullets = sentences[:6]
    if not bullets:
        return "Não encontrei trechos suficientes para montar um resumo seguro."
    return "\n".join(f"- {b}" for b in bullets)


def _fallback_quiz(sentences: list[str], show_answers: bool = False) -> str:
    base = _unique_keep_order(sentences)[:5]
    if not base:
        return "Não encontrei base suficiente para criar questões com segurança."
    questions = []
    correct_cycle = ["A", "C", "B", "D", "A"]
    distractors = [
        "Uma afirmação que não aparece nos trechos recuperados.",
        "Um exemplo externo não usado como fonte pelo documento.",
        "Uma conclusão ampla demais para ser sustentada pelo contexto.",
    ]
    for i, sentence in enumerate(base):
        words = [w for w in re.findall(r"[A-Za-zÀ-ÿ]{5,}", sentence) if normalize(w) not in {"sobre", "entre", "tambem", "também", "documento", "conceito", "sistema"}]
        keyword = words[0] if words else f"conceito {i+1}"
        correct = correct_cycle[i % len(correct_cycle)]
        correct_text = sentence[:150] + ("..." if len(sentence) > 150 else "")
        labels = ["A", "B", "C", "D"]
        options = {}
        d_iter = iter(distractors)
        for label in labels:
            if label == correct:
                options[label] = correct_text
            else:
                options[label] = next(d_iter, "Uma alternativa sem base nos trechos.")
        questions.append({
            "question": f"Segundo o documento, qual alternativa melhor representa {keyword}?",
            "options": options,
            "correct": correct,
            "explanation": "A alternativa correta é a única diretamente apoiada pelo trecho recuperado do documento.",
        })
    quiz = {
        "type": "interactive_quiz",
        "title": "Questionário interativo",
        "show_answers": show_answers,
        "questions": _dedupe_quiz_questions(questions),
    }
    return _quiz_json_block(quiz)


def _fallback_plan(sentences: list[str]) -> str:
    topics = []
    for s in sentences[:6]:
        topic = s[:90].rstrip(".,;:")
        if topic not in topics:
            topics.append(topic)
    if not topics:
        return "Não encontrei base suficiente para montar plano de estudo."
    return "\n".join(f"{i}. Estude: {topic}. Depois, faça uma anotação curta e crie 2 perguntas de revisão." for i, topic in enumerate(topics, start=1))


def _fallback_flowchart(sentences: list[str]) -> str:
    labels = []
    for s in sentences[:5]:
        label = re.sub(r"[^A-Za-zÀ-ÿ0-9 ]", "", s)[:42].strip() or "Conceito"
        labels.append(label)
    if len(labels) < 2:
        labels = ["Ler documento", "Identificar conceitos", "Revisar conteúdo"]
    nodes = [f"    A{i}[{label}]" for i, label in enumerate(labels, start=1)]
    edges = [f"    A{i} --> A{i+1}" for i in range(1, len(labels))]
    return "```mermaid\nflowchart TD\n" + "\n".join(nodes + edges) + "\n```"


def _fallback_flashcards(sentences: list[str]) -> str:
    if not sentences:
        return "Não encontrei base suficiente para gerar flashcards."
    cards = []
    for i, s in enumerate(sentences[:6], start=1):
        cards.append(f"**Card {i}**\nPergunta: O que o trecho indica sobre o tema?\nResposta: {s}")
    return "\n\n".join(cards)


def _fallback_answer(plan: AgentPlan, docs: list[dict], context: str, error: str | None = None) -> str:
    sentences = _extract_context_sentences(context)
    doc_lines = "\n".join(f"- {d.get('filename') or d.get('original_filename')}" for d in docs)
    parts = ["Consegui recuperar trechos dos documentos, mas a chamada de IA real não foi concluída. Vou entregar uma versão segura baseada apenas no contexto recuperado."]

    if plan.out_of_scope_risk and plan.tasks == ["free_question"]:
        return f"""Não encontrei base suficiente nos documentos selecionados para responder com segurança a esse pedido.

Posso ajudar com perguntas, resumo, revisão ou plano de estudo sobre as fontes selecionadas.

## Fontes usadas
{doc_lines}"""

    for task in plan.tasks:
        if task == "summary":
            parts.append("## Resumo\n" + _fallback_summary(sentences))
        elif task == "quiz":
            parts.append("## Questionário\n" + _fallback_quiz(sentences))
        elif task == "study_plan":
            parts.append("## Plano de estudo\n" + _fallback_plan(sentences))
        elif task == "flowchart":
            parts.append("## Fluxograma\n" + _fallback_flowchart(sentences))
        elif task == "flashcards":
            parts.append("## Flashcards\n" + _fallback_flashcards(sentences))
        elif task == "quick_review":
            parts.append("## Revisão rápida\n" + _fallback_summary(sentences[:5]))
        elif task == "compare_docs":
            if len(docs) < 2:
                parts.append("## Comparação\nPara comparar documentos, selecione pelo menos duas fontes. Com uma fonte, consigo apenas resumir ou revisar o conteúdo dela.")
            else:
                parts.append("## Comparação\nOs trechos recuperados indicam conteúdos de mais de uma fonte. Para uma comparação mais precisa, refine o pedido com os temas que deseja comparar.")
        elif task == "explain_simple":
            parts.append("## Explicação simples\n" + _fallback_summary(sentences[:4]))
        else:
            parts.append("## Resposta baseada nos documentos\n" + _fallback_summary(sentences[:4]))

    parts.append("## Fontes usadas\n" + doc_lines)
    if error:
        parts.append("\n> Observação técnica para debug: a IA real falhou, mas a resposta acima não usou informação externa.")
    return "\n\n".join(parts)


def _material_type(task: str) -> str:
    # O schema Supabase aceita `free_answer`, não `free_question`.
    # Mantemos `free_question` só como tarefa interna do agente.
    if task == "compare_docs":
        return "comparison"
    if task in {"explain_simple", "free_question"}:
        return "free_answer"
    return task


def _save_generated_materials(user_id, notebook_id, docs: list[dict], tasks: list[str], content: str) -> None:
    primary_doc_id = docs[0]["id"] if docs else None
    for task in tasks:
        if task not in MATERIAL_TASKS:
            continue
        material_type = _material_type(task)
        title = f"{TASK_LABELS.get(task, task).capitalize()} gerado pelo agente"
        try:
            if is_postgres():
                execute(
                    """
                    INSERT INTO generated_materials (user_id, notebook_id, document_id, type, title, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, notebook_id, primary_doc_id, material_type, title, content),
                )
            else:
                execute(
                    """
                    INSERT INTO generated_materials (notebook_id, document_id, type, title, content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (notebook_id, primary_doc_id, material_type, title, content),
                )
        except Exception as exc:
            _log(f"Falha ao salvar generated_material task={task}: {exc}")


def build_agent_answer(
    notebook_id,
    message: str,
    selected_document_ids: list | None = None,
    user_id: str | int = "1",
) -> dict:
    mapped_user = map_user_id(user_id)
    mapped_notebook = map_notebook_id(notebook_id)
    _log(f"Mensagem recebida: {message!r}")
    docs = get_documents(mapped_notebook, selected_document_ids, user_id=mapped_user)
    _log(f"Documentos encontrados/selecionados: {len(docs)}")
    plan = build_plan(message, docs)
    _log(f"Tarefas detectadas: {plan.tasks}")
    _log(f"Modo escolhido: {plan.mode}")

    if not docs:
        available_docs = _all_processed_documents(mapped_notebook, mapped_user, limit=8)
        if available_docs:
            names = "\n".join(f"- {d.get('filename') or d.get('original_filename')}" for d in available_docs)
            answer = (
                "Encontrei mais de um documento neste notebook, mas nenhum arquivo foi selecionado para esta pergunta.\n\n"
                "Marque uma ou mais fontes na lista lateral e envie o comando novamente. Assim eu evito misturar PDFs por engano.\n\n"
                f"## Fontes disponíveis\n{names}"
            )
        else:
            answer = (
                "Ainda não encontrei nenhum documento selecionado neste notebook.\n\n"
                "Envie ou selecione pelo menos um PDF, DOCX ou TXT para eu analisar. "
                "Eu só vou gerar respostas com base nas fontes enviadas."
            )
        return {"answer": answer, "tasks": plan.tasks, "mode": plan.mode, "documents": [], "context_preview": "", "llm": provider_info()}

    doc_ids = [d["id"] for d in docs]
    context, used_chunks = build_context_for_documents(mapped_notebook, doc_ids, message, limit_per_doc=8 if len(docs) == 1 else 6, max_chars=14500)
    coverage = context_coverage_report(used_chunks)
    _log(f"Chunks usados no contexto: {len(used_chunks)} coverage={coverage}")

    if not context.strip():
        answer = (
            "Não encontrei base suficiente nos documentos selecionados para responder com segurança.\n\n"
            "O arquivo pode estar vazio, protegido ou ter sido processado sem texto útil."
        )
        return {
            "answer": answer,
            "tasks": plan.tasks,
            "mode": plan.mode,
            "documents": [{"id": d["id"], "filename": d.get("filename"), "status": d.get("status", "processed")} for d in docs],
            "context_preview": "",
            "chunks_used": 0,
            "coverage": coverage,
            "llm": provider_info(),
        }

    # Bloqueio determinístico de pedidos obviamente fora do documento, sem gastar tokens.
    if _should_block_out_of_scope(message, context, plan):
        _log("Pedido fora do escopo dos documentos bloqueado antes da chamada ao LLM.")
        answer = _fallback_answer(plan, docs, context)
        return {
            "answer": answer,
            "tasks": plan.tasks,
            "mode": plan.mode,
            "documents": [{"id": d["id"], "filename": d.get("filename"), "status": d.get("status", "processed")} for d in docs],
            "context_preview": context[:1200],
            "chunks_used": len(used_chunks),
            "coverage": coverage,
            "llm": {**provider_info(), "ok": False, "blocked_out_of_scope": True},
        }

    user_prompt = _build_user_prompt(message, plan, docs, context, coverage)
    llm = call_llm(_system_prompt(), user_prompt, max_tokens=3200 if len(plan.tasks) > 1 else 2000)

    if llm.ok:
        answer = (llm.text or "").strip()
    else:
        answer = _fallback_answer(plan, docs, context, llm.error)

    # Guardrail crítico para produção: nunca devolver resposta vazia ao SSE.
    # Em deploys com proxy, uma resposta vazia faz o frontend acusar "terminou sem conteúdo".
    if not str(answer or "").strip():
        _log("LLM/agente retornou texto vazio; usando fallback local seguro.")
        answer = _fallback_answer(plan, docs, context, "Resposta vazia do provider de IA.")

    if "quiz" in plan.tasks:
        answer = _normalize_interactive_quiz_blocks(answer, _quiz_user_requested_answers(message))
        if not str(answer or "").strip():
            _log("Normalização do quiz resultou vazia; usando fallback local de quiz.")
            sentences = _extract_context_sentences(context)
            answer = "## Questionário\n" + _fallback_quiz(sentences, _quiz_user_requested_answers(message))

    if not str(answer or "").strip():
        answer = "Não encontrei base suficiente nos documentos selecionados para responder com segurança."

    _save_generated_materials(mapped_user, mapped_notebook, docs, plan.tasks, answer)

    return {
        "answer": answer,
        "tasks": plan.tasks,
        "mode": plan.mode,
        "documents": [{"id": d["id"], "filename": d.get("filename"), "status": d.get("status", "processed")} for d in docs],
        "context_preview": context[:1200],
        "chunks_used": len(used_chunks),
        "coverage": coverage,
        "llm": {"provider": llm.provider, "model": llm.model, "ok": llm.ok, "error": llm.error, "tried_fallback": llm.tried_fallback},
    }


def stream_steps(result: dict | None = None, pre: bool = False) -> list[str]:
    if pre:
        return [
            "🔎 Verificando fontes selecionadas...",
            "🧠 Interpretando pedido e detectando tarefas...",
            "📚 Recuperando contexto no banco sem carregar o PDF inteiro...",
            "🛠️ Preparando execução multi-função do agente...",
        ]
    docs = (result or {}).get("documents") or []
    tasks = (result or {}).get("tasks") or []
    mode = (result or {}).get("mode") or "desconhecido"
    chunks = (result or {}).get("chunks_used", 0)
    llm = (result or {}).get("llm", {})
    coverage = (result or {}).get("coverage", {})
    return [
        f"📄 Documentos usados: {len(docs)}.",
        f"🧭 Modo de análise: {mode}.",
        f"🧠 Tarefas detectadas: {', '.join(TASK_LABELS.get(t, t) for t in tasks)}.",
        f"📚 Chunks usados no contexto: {chunks}.",
        f"📊 Cobertura: {coverage.get('documents', len(docs))} documento(s), qualidade média {coverage.get('avg_info_score', 0)}.",
        f"🤖 IA: {llm.get('provider', 'mock')} / {llm.get('model', 'mock')}.",
        "✍️ Gerando resposta baseada somente nos documentos...",
    ]
