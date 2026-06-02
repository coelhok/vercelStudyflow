from pathlib import Path


def read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_pdf(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
        text = []
        with fitz.open(path) as doc:
            for page in doc:
                text.append(page.get_text())
        return "\n".join(text)
    except Exception as exc:
        return f"[Erro ao ler PDF: {exc}]"


def read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        return f"[Erro ao ler DOCX: {exc}]"


def read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".docx":
        return read_docx(path)
    if suffix == ".txt":
        return read_txt(path)
    raise ValueError("Tipo de arquivo não suportado.")


def chunk_text(text: str, size: int = 900, overlap: int = 120):
    """Divide texto em chunks sem loop infinito.

    Correção Build 4.1: a versão anterior voltava para `end - overlap`
    mesmo quando chegava no fim do texto. Em textos grandes isso podia repetir
    o último trecho para sempre e travar a máquina.
    """
    clean = " ".join((text or "").split())
    chunks: list[str] = []
    if not clean:
        return chunks

    if overlap >= size:
        overlap = max(0, size // 5)

    start = 0
    text_len = len(clean)
    while start < text_len:
        end = min(start + size, text_len)
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks
