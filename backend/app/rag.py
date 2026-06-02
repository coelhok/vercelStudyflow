from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from statistics import mean

from app.database import fetch_all

STOPWORDS = {
    "para", "como", "esse", "essa", "isso", "com", "uma", "uns", "das", "dos", "que", "por", "mais",
    "quero", "faça", "faca", "gere", "gerar", "documento", "pdf", "doc", "texto", "sobre", "base", "selecionado",
    "resumo", "questionario", "questionário", "plano", "estudo", "fluxograma", "flashcards", "revisao", "revisão",
    "depois", "monte", "crie", "fazer", "analise", "analisar", "deste", "dessa", "desse", "neste", "nesta",
    "qual", "quais", "quando", "onde", "porque", "entao", "então", "tambem", "também", "voce", "você",
}

STRUCTURAL_TERMS = [
    "objetivo", "objetivos", "aprendizado", "introdução", "introducao", "conclusão", "conclusao",
    "resumo", "unidade", "sumário", "sumario", "apresentação", "apresentacao", "conceitos", "fundamentos",
]

TASK_TERMS = {
    "summary": ["objetivo", "introdução", "conclusão", "resumo", "conceitos", "fundamentos", "apresentação"],
    "quiz": ["objetivo", "conceitos", "métodos", "metodos", "técnicas", "tecnicas", "exemplo", "aplicações", "aplicacoes"],
    "study_plan": ["objetivo", "conteúdo", "conteudo", "unidade", "aprendizado", "introdução", "conclusão"],
    "flowchart": ["processo", "etapas", "modelo", "métodos", "metodos", "sistema", "aplicação", "aplicacao"],
    "compare_docs": ["objetivo", "introdução", "conceitos", "modelos", "métodos", "metodos", "avaliação", "avaliacao"],
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def extract_query_terms(query: str) -> list[str]:
    normalized = normalize(query)
    terms = []
    for word in re.findall(r"[a-z0-9]{4,}", normalized):
        if word not in STOPWORDS and word not in terms:
            terms.append(word)
    return terms[:24]


def _info_score(text: str) -> float:
    if not text:
        return 0.0
    letters = re.findall(r"[A-Za-zÀ-ÿ]", text)
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", text)
    unique = len(set(normalize(" ".join(words)).split()))
    dot_noise = text.count(".") / max(1, len(text))
    return (len(letters) / max(1, len(text))) + min(unique / 80, 1.0) - min(dot_noise * 2, 0.5)


def _score_chunk(row: dict, terms: list[str], task_hints: list[str]) -> float:
    text = normalize(row.get("content") or "")
    idx = int(row.get("chunk_index") or 0)
    score = 0.0
    score += _info_score(row.get("content") or "")
    for term in terms:
        if term in text:
            score += 3.0
    for hint in task_hints:
        if normalize(hint) in text:
            score += 1.5
    for marker in STRUCTURAL_TERMS:
        if normalize(marker) in text:
            score += 0.65
    if idx <= 2:
        score += 0.7
    # Sumários cheios de pontinhos costumam ser menos úteis que conteúdo explicativo.
    if text.count(" .") > 8 or (row.get("content") or "").count(". . .") > 2:
        score -= 1.0
    return score


def detect_task_hints(query: str) -> list[str]:
    q = normalize(query)
    hints: list[str] = []
    for task, words in TASK_TERMS.items():
        if task == "summary" and any(x in q for x in ["resumo", "resuma", "sintese", "síntese"]):
            hints.extend(words)
        if task == "quiz" and any(x in q for x in ["quest", "quiz", "pergunta"]):
            hints.extend(words)
        if task == "study_plan" and any(x in q for x in ["plano", "cronograma", "estudo"]):
            hints.extend(words)
        if task == "flowchart" and any(x in q for x in ["fluxograma", "diagrama", "fluxo"]):
            hints.extend(words)
        if task == "compare_docs" and any(x in q for x in ["compar", "diferen", "semelhan"]):
            hints.extend(words)
    if not hints:
        hints = STRUCTURAL_TERMS[:]
    unique = []
    for h in hints:
        if h not in unique:
            unique.append(h)
    return unique


def search_chunks(notebook_id, query: str, document_ids: list | None = None, limit: int = 10):
    terms = extract_query_terms(query)
    hints = detect_task_hints(query)
    params: list = [notebook_id]
    doc_filter = ""
    if document_ids:
        placeholders = ",".join(["?"] * len(document_ids))
        doc_filter = f" AND document_chunks.document_id IN ({placeholders})"
        params.extend(document_ids)

    chunks = fetch_all(
        f"""
        SELECT document_chunks.id, document_chunks.document_id, document_chunks.notebook_id,
               document_chunks.content, document_chunks.page_number, document_chunks.chunk_index,
               documents.filename
        FROM document_chunks
        JOIN documents ON documents.id = document_chunks.document_id
        WHERE document_chunks.notebook_id = ? {doc_filter}
        ORDER BY document_chunks.document_id ASC, document_chunks.chunk_index ASC
        LIMIT 900
        """,
        params,
    )

    scored = []
    for c in chunks:
        score = _score_chunk(c, terms, hints)
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [dict(c, score=round(score, 3)) for score, c in scored[:limit] if score > 0]


def _pick_evenly(rows: list[dict], count: int) -> list[dict]:
    if not rows or count <= 0:
        return []
    if len(rows) <= count:
        return rows[:]
    positions = sorted(set(round(i * (len(rows) - 1) / max(1, count - 1)) for i in range(count)))
    return [rows[p] for p in positions]


def build_context_for_documents(notebook_id, document_ids: list, query: str, limit_per_doc: int = 7, max_chars: int = 14500) -> tuple[str, list[dict]]:
    """Monta contexto controlado e mais representativo. Nunca retorna o PDF inteiro."""
    params: list = [notebook_id]
    doc_filter = ""
    if document_ids:
        placeholders = ",".join(["?"] * len(document_ids))
        doc_filter = f" AND document_chunks.document_id IN ({placeholders})"
        params.extend(document_ids)

    rows = fetch_all(
        f"""
        SELECT document_chunks.id, document_chunks.document_id, document_chunks.content,
               document_chunks.page_number, document_chunks.chunk_index, documents.filename
        FROM document_chunks
        JOIN documents ON documents.id = document_chunks.document_id
        WHERE document_chunks.notebook_id = ? {doc_filter}
        ORDER BY document_chunks.document_id ASC, document_chunks.chunk_index ASC
        LIMIT 1200
        """,
        params,
    )

    relevant = search_chunks(notebook_id, query, document_ids=document_ids, limit=max(12, limit_per_doc * max(1, len(document_ids))))
    relevant_by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in relevant:
        relevant_by_doc[str(r["document_id"])].append(r)

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_doc[str(row["document_id"])].append(row)

    selected: list[dict] = []
    seen = set()

    def add(row: dict, reason: str, score: float | None = None):
        key = str(row["id"])
        if key in seen:
            return
        text = row.get("content") or ""
        if _info_score(text) < 0.25:
            return
        new = dict(row)
        new["reason"] = reason
        if score is not None:
            new["score"] = score
        selected.append(new)
        seen.add(key)

    for doc_id, doc_rows in by_doc.items():
        doc_rows = sorted(doc_rows, key=lambda r: int(r.get("chunk_index") or 0))
        # 1) começo útil, mas sem dominar o contexto.
        for row in doc_rows[:2]:
            add(row, "início útil do documento")
        # 2) amostra distribuída evita resumo só de capa/sumário.
        for row in _pick_evenly(doc_rows[2:], 3):
            add(row, "amostra distribuída do documento")
        # 3) chunks lexicalmente relevantes.
        for r in relevant_by_doc.get(doc_id, [])[:limit_per_doc]:
            add(r, "trecho mais relevante para o pedido", r.get("score"))
        # 4) marcadores estruturais importantes.
        for row in doc_rows:
            if sum(1 for m in STRUCTURAL_TERMS if normalize(m) in normalize(row.get("content") or "")) >= 2:
                add(row, "trecho estrutural do material")
            if len([s for s in selected if str(s["document_id"]) == doc_id]) >= limit_per_doc:
                break

    # Limite por documento, preservando diversidade.
    final_selection: list[dict] = []
    for doc_id, _rows in by_doc.items():
        doc_selected = [s for s in selected if str(s["document_id"]) == doc_id]
        # Ordena por razão e score, mas mantém alguma ordem didática por chunk.
        doc_selected.sort(key=lambda s: (-(float(s.get("score") or 0)), int(s.get("chunk_index") or 0)))
        final_selection.extend(sorted(doc_selected[:limit_per_doc], key=lambda s: int(s.get("chunk_index") or 0)))

    parts = []
    total = 0
    final_chunks = []
    for row in final_selection:
        content = (row.get("content") or "").strip()
        if not content:
            continue
        block = f"[Fonte: {row.get('filename')} | chunk {row.get('chunk_index')} | motivo: {row.get('reason')} | score: {row.get('score', '-')}]\n{content}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        final_chunks.append(row)
        total += len(block)

    return "\n\n---\n\n".join(parts), final_chunks


def context_coverage_report(chunks: list[dict]) -> dict:
    if not chunks:
        return {"chunks": 0, "documents": 0, "avg_info_score": 0}
    return {
        "chunks": len(chunks),
        "documents": len({str(c.get("document_id")) for c in chunks}),
        "avg_info_score": round(mean(_info_score(c.get("content") or "") for c in chunks), 3),
    }
