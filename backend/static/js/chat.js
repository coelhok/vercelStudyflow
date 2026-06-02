const chatForm = document.getElementById('chatForm');
const input = document.getElementById('messageInput');
const chatBox = document.getElementById('chatBox');

if (chatForm) {
  chatForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    addMessage('user', text);
    await sendChatStream(text);
  });
}

document.querySelectorAll('.quick-actions button[data-prompt]').forEach(btn => {
  btn.addEventListener('click', () => {
    const prompt = (btn.dataset.prompt || '').trim();
    if (!prompt) {
      console.warn('[CHAT] Ação rápida ignorada: botão sem data-prompt.');
      return;
    }
    if (!input || !chatForm) return;
    input.value = prompt;
    chatForm.requestSubmit();
  });
});

document.addEventListener('click', async (event) => {
  const copyBtn = event.target.closest('[data-copy-target]');
  if (!copyBtn) return;
  const selector = copyBtn.dataset.copyTarget;
  const target = selector ? document.querySelector(selector) : null;
  const text = target?.dataset.raw || target?.innerText || '';
  if (!text.trim()) return;
  try {
    await navigator.clipboard.writeText(text);
    copyBtn.textContent = 'Copiado';
    setTimeout(() => (copyBtn.textContent = copyBtn.dataset.label || 'Copiar'), 1500);
  } catch (err) {
    console.error('[CHAT][COPY][ERRO]', err);
  }
});

document.addEventListener('change', (event) => {
  const input = event.target.closest('.quiz-option input[type="radio"]');
  if (!input) return;
  const question = input.closest('.quiz-question');
  if (!question || question.closest('.quiz-form-card')?.classList.contains('graded')) return;
  question.querySelectorAll('.quiz-option').forEach(option => option.classList.remove('selected'));
  input.closest('.quiz-option')?.classList.add('selected');
});

document.addEventListener('click', (event) => {
  const submit = event.target.closest('[data-quiz-submit]');
  if (submit) {
    const card = submit.closest('.quiz-form-card');
    if (card) gradeQuizCard(card);
    return;
  }
  const answerBtn = event.target.closest('[data-quiz-answer]');
  if (answerBtn) {
    const card = answerBtn.closest('.quiz-form-card');
    if (card) revealQuizAnswers(card);
    return;
  }
  const reset = event.target.closest('[data-quiz-reset]');
  if (reset) {
    const card = reset.closest('.quiz-form-card');
    if (card) resetQuizCard(card);
  }
});

function formatMessageTime(value) {
  if (!value) return 'agora';
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'salvo';
    return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return 'salvo';
  }
}

function addMessage(role, content, options = {}) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const when = options.created_at ? formatMessageTime(options.created_at) : 'agora';
  div.innerHTML = role === 'assistant'
    ? `<div class="avatar">✦</div><div class="bubble">${formatContent(content)}<small>${escapeHtml(when)}</small></div>`
    : `<div class="bubble">${escapeHtml(content)}<small>${escapeHtml(when)}</small></div>`;
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
  setTimeout(renderMermaidBlocks, 0);
  return div;
}

function renderWelcomeMessage() {
  if (!chatBox) return;
  chatBox.innerHTML = `
    <div class="msg assistant">
      <div class="avatar">✦</div>
      <div class="bubble">
        <p>Olá! Sou o seu Agente de IA do StudyFlow.</p>
        <p>Posso analisar um ou vários PDFs, DOCX e TXT selecionados. Eu vou mostrar meu processo em tempo real: fontes usadas, etapa atual e modo de análise.</p>
        <p><strong>Escolha suas fontes e diga o que você quer que eu faça.</strong></p>
        <small>início</small>
      </div>
    </div>`;
}

async function loadChatHistory(options = {}) {
  if (!chatBox || !state.notebookId) return;
  const historyKey = `${state.userId}:${state.notebookId}`;
  if (!options.force && chatBox.dataset.historyKey === historyKey && chatBox.dataset.historyLoaded === 'true') {
    console.log('[CHAT][HISTORY] Histórico já carregado para este notebook.');
    return;
  }

  console.log('[CHAT][HISTORY] Carregando histórico:', { notebookId: state.notebookId });
  try {
    const messages = await api(`/chat/history/${encodeURIComponent(state.notebookId)}`);
    renderWelcomeMessage();
    if (Array.isArray(messages) && messages.length) {
      messages.forEach(msg => {
        if (msg.role === 'user' || msg.role === 'assistant') {
          addMessage(msg.role, msg.content || '', { created_at: msg.created_at });
        }
      });
      updateAgentState?.('done', 'Sessão restaurada', `${messages.length} mensagem(ns) carregada(s) do histórico.`, 'histórico');
    } else {
      updateAgentState?.('idle', 'Agente pronto', 'Nenhuma mensagem antiga nesta sessão. Selecione fontes e envie um comando.', 'aguardando');
    }
    chatBox.dataset.historyKey = historyKey;
    chatBox.dataset.historyLoaded = 'true';
    await renderMermaidBlocks();
  } catch (err) {
    console.error('[CHAT][HISTORY][ERRO] Não foi possível carregar histórico:', err);
    renderWelcomeMessage();
    updateAgentState?.('error', 'Histórico indisponível', 'Não consegui carregar mensagens antigas desta sessão.', 'erro');
  }
}

function resetChatHistoryState() {
  if (!chatBox) return;
  chatBox.dataset.historyKey = '';
  chatBox.dataset.historyLoaded = 'false';
  renderWelcomeMessage();
}

function getSelectedDocumentIds() {
  const availableIds = [...document.querySelectorAll('.doc-check')].map(el => String(el.value));
  const checked = [...document.querySelectorAll('.doc-check:checked')].map(el => String(el.value));
  const validChecked = checked.filter(id => availableIds.includes(id));
  const staleState = (state.selectedDocumentIds || []).filter(id => !availableIds.includes(String(id)));
  if (staleState.length) {
    console.warn('[CHAT] IDs de documentos removidos/obsoletos foram limpos:', staleState);
  }
  setSelectedDocumentIds(validChecked);
  updateSelectedCount?.();
  return validChecked;
}

async function sendChatStream(message) {
  const selectedIds = getSelectedDocumentIds();
  console.log('[CHAT] Mensagem digitada:', message);
  console.log('[CHAT] Documentos selecionados após limpeza:', selectedIds);
  if (!selectedIds.length) console.log('[CHAT] Nenhum checkbox marcado; backend pode usar fallback controlado do último documento processado.');

  const placeholder = document.createElement('div');
  placeholder.className = 'msg assistant';
  placeholder.innerHTML = `
    <div class="avatar">✦</div>
    <div class="bubble">
      <div class="agent-progress">
        <strong>Agente trabalhando...</strong>
        <ul class="agent-steps" id="agentSteps-${Date.now()}"></ul>
      </div>
      <div class="stream-content"></div>
      <small>agora</small>
    </div>`;
  chatBox.appendChild(placeholder);
  const stepsList = placeholder.querySelector('.agent-steps');
  const contentBox = placeholder.querySelector('.stream-content');
  let finalText = '';

  updateAgentState('working', 'Agente trabalhando', 'Iniciando análise do pedido...', 'processando');

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);

  try {
    console.log('[CHAT] Chamando API stream...');
    const res = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        notebook_id: state.notebookId,
        message,
        selected_document_ids: selectedIds,
      }),
      signal: controller.signal,
    });

    console.log('[CHAT] Status da resposta:', res.status);
    if (!res.ok || !res.body) {
      const errText = await res.text();
      console.error('[CHAT][ERRO] Resposta inválida:', res.status, errText);
      throw new Error(errText || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const evt of events) {
        const line = evt.split('\n').find(l => l.startsWith('data:'));
        if (!line) continue;
        const raw = line.replace(/^data:\s?/, '');
        try {
          const payload = JSON.parse(raw);
          console.log('[CHAT][STREAM]', payload);
          if (payload.type === 'status') {
            const li = document.createElement('li');
            li.textContent = payload.message;
            stepsList.appendChild(li);
            updateAgentState('working', 'Agente trabalhando', payload.message, 'streaming');
          }
          if (payload.type === 'content') {
            finalText += payload.message;
            contentBox.innerHTML = formatContent(finalText, { streaming: true });
            chatBox.scrollTop = chatBox.scrollHeight;
          }
          if (payload.type === 'done') {
            updateAgentState('done', 'Agente finalizado', payload.message, 'concluído');
          }
        } catch (err) {
          console.error('[CHAT][STREAM][JSON][ERRO]', err, raw);
        }
      }
    }

    if (!finalText.trim()) {
      finalText = 'O agente terminou a execução sem enviar conteúdo final. Tente reenviar a pergunta ou peça uma tarefa menor. Se persistir, verifique /api/health/runtime-check e os logs do servidor.';
      updateAgentState('error', 'Resposta vazia do agente', 'O stream terminou sem conteúdo final.', 'erro');
    }
    contentBox.innerHTML = formatContent(finalText, { streaming: false });
    await renderMermaidBlocks();
  } catch (err) {
    console.error('[CHAT][ERRO] Erro ao enviar mensagem:', err);
    contentBox.innerHTML = '<p>Não consegui concluir a resposta. Verifique o console e o terminal do FastAPI.</p>';
    updateAgentState('error', 'Erro no agente', 'Não consegui concluir a resposta. Veja o console para detalhes.', 'erro');
  } finally {
    clearTimeout(timeout);
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

function normalizeMermaidFences(text) {
  const lines = String(text || '').split('\n');
  const out = [];
  let i = 0;
  let insideFence = false;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (trimmed.startsWith('```')) {
      insideFence = !insideFence;
      out.push(line);
      i += 1;
      continue;
    }
    if (!insideFence && /^(graph|flowchart)\s+(TD|LR|BT|RL)/i.test(trimmed)) {
      const block = [trimmed];
      i += 1;
      while (i < lines.length) {
        const current = lines[i];
        const t = current.trim();
        if (!t || t.startsWith('## ') || /^(Explicação|Conclusão|Fontes usadas|Este fluxograma|Esse fluxograma)/i.test(t)) break;
        if (/^[-*]\s/.test(t) && !/[\[\]{}()<>-]/.test(t)) break;
        block.push(current);
        i += 1;
      }
      out.push('```mermaid');
      out.push(block.join('\n'));
      out.push('```');
      continue;
    }
    out.push(line);
    i += 1;
  }
  return out.join('\n');
}

function stripEmptyFlowchartHeadingBeforeMermaid(text) {
  // Build 5.4: evita card duplicado de Fluxograma quando o LLM retorna
  // "## Fluxograma" imediatamente antes do bloco Mermaid.
  return String(text || '')
    .replace(/(^|\n)##\s*(Fluxograma|Diagrama)\s*\n+(?=```mermaid)/gi, '\n')
    .replace(/(^|\n)##\s*(Fluxograma|Diagrama)\s*\n+$/gi, '\n');
}


function normalizeQuizFences(text) {
  const source = String(text || '');
  if (!source.trim()) return '';

  let normalized = source
    .replace(/```\s*questionario/gi, '```quiz')
    .replace(/```\s*quiz\s*\n/gi, '```quiz\n')
    .replace(/```\s*json\s*\n/gi, '```json\n');

  // Se o modelo devolver JSON puro de quiz sem fence, embrulha em ```quiz.
  const trimmed = normalized.trim();
  if (!/```\s*(quiz|json)/i.test(trimmed) && /"type"\s*:\s*"interactive_quiz"/i.test(trimmed)) {
    const firstBrace = trimmed.indexOf('{');
    const lastBrace = trimmed.lastIndexOf('}');
    if (firstBrace >= 0 && lastBrace > firstBrace) {
      const before = trimmed.slice(0, firstBrace).trim();
      const json = trimmed.slice(firstBrace, lastBrace + 1).trim();
      const after = trimmed.slice(lastBrace + 1).trim();
      normalized = `${before ? `${before}\n\n` : ''}\`\`\`quiz\n${json}\n\`\`\`${after ? `\n\n${after}` : ''}`;
    }
  }

  return normalized;
}

function hideIncompleteQuizFenceDuringStreaming(text) {
  const source = String(text || '');
  const fenceRegex = /```\s*(quiz|json)\s*\n/gi;
  let match;
  let lastMatch = null;
  while ((match = fenceRegex.exec(source)) !== null) lastMatch = match;
  if (!lastMatch) return source;

  const afterOpening = source.slice(lastMatch.index + lastMatch[0].length);
  if (afterOpening.includes('```')) return source;

  const before = source.slice(0, lastMatch.index).trimEnd();
  return `${before}\n\n<section class="material-card quiz quiz-loading-card"><div class="material-head"><span class="material-icon">▦</span><strong>Questionário</strong></div><p>Gerando questionário interativo...</p></section>`;
}

function formatContent(text, options = {}) {
  let normalized = stripEmptyFlowchartHeadingBeforeMermaid(normalizeMermaidFences(text));
  normalized = normalizeQuizFences(normalized);
  if (options.streaming) normalized = hideIncompleteQuizFenceDuringStreaming(normalized);
  const tokens = [];
  const regex = /```(mermaid|quiz|json)\s*([\s\S]*?)```/gi;
  let lastIndex = 0;
  let match;
  while ((match = regex.exec(normalized)) !== null) {
    if (match.index > lastIndex) tokens.push({ type: 'text', value: normalized.slice(lastIndex, match.index) });
    const fenceType = String(match[1] || '').toLowerCase();
    const raw = match[2].trim();
    if (fenceType === 'mermaid') {
      tokens.push({ type: 'mermaid', value: raw });
    } else {
      const quiz = parseQuizPayload(raw);
      if (quiz) tokens.push({ type: 'quiz', value: quiz, raw });
      else tokens.push({ type: 'text', value: match[0] });
    }
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < normalized.length) tokens.push({ type: 'text', value: normalized.slice(lastIndex) });

  return tokens.map(token => {
    if (token.type === 'mermaid') return renderMermaidCard(token.value);
    if (token.type === 'quiz') return renderInteractiveQuiz(token.value);
    return renderTextCards(token.value, options);
  }).join('');
}

function renderTextCards(text, options = {}) {
  const clean = String(text || '').trim();
  if (!clean) return '';

  const parts = splitMarkdownSections(clean);
  if (parts.length <= 1 && !/^##\s+/m.test(clean)) {
    return `<div class="answer-text">${inlineMarkdown(escapeHtml(clean)).replace(/\n/g, '<br>')}</div>`;
  }

  const usableParts = parts.filter(section => {
    const type = classifySection(section.title);
    const body = String(section.body || '').trim();
    // Build 5.4: não cria card vazio de Fluxograma se o Mermaid já virou card visual.
    return !(type === 'flowchart' && !body);
  });
  if (!usableParts.length) return '';
  return `<div class="material-grid">${usableParts.map(section => {
    const type = classifySection(section.title);
    const title = section.title || 'Resposta';
    const body = inlineMarkdown(escapeHtml(section.body || '')).replace(/\n/g, '<br>');
    return `
      <section class="material-card ${type}">
        <div class="material-head">
          <span class="material-icon">${iconFor(type)}</span>
          <strong>${escapeHtml(title)}</strong>
        </div>
        <div class="material-body">${body}</div>
      </section>`;
  }).join('')}</div>`;
}

function splitMarkdownSections(text) {
  const lines = String(text || '').split('\n');
  const sections = [];
  let current = { title: '', body: [] };
  for (const line of lines) {
    const m = line.match(/^##\s+(.+)\s*$/);
    if (m) {
      if (current.title || current.body.join('\n').trim()) sections.push({ title: current.title, body: current.body.join('\n').trim() });
      current = { title: m[1].trim(), body: [] };
    } else {
      current.body.push(line);
    }
  }
  if (current.title || current.body.join('\n').trim()) sections.push({ title: current.title, body: current.body.join('\n').trim() });
  return sections;
}

function classifySection(title) {
  const t = normalizeString(title);
  if (t.includes('resumo')) return 'summary';
  if (t.includes('questionario') || t.includes('quiz')) return 'quiz';
  if (t.includes('plano')) return 'study-plan';
  if (t.includes('fluxograma') || t.includes('diagrama')) return 'flowchart';
  if (t.includes('flashcard')) return 'flashcards';
  if (t.includes('revisao')) return 'review';
  if (t.includes('fonte')) return 'sources';
  return 'generic';
}

function iconFor(type) {
  return ({
    summary: '▣', quiz: '▦', 'study-plan': '▥', flowchart: '▤', flashcards: '▧', review: '⚡', sources: '⌁', generic: '✦'
  })[type] || '✦';
}

function parseQuizPayload(raw) {
  const original = String(raw || '').trim();
  const attempts = [];
  attempts.push(original);

  const firstBrace = original.indexOf('{');
  const lastBrace = original.lastIndexOf('}');
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    attempts.push(original.slice(firstBrace, lastBrace + 1));
  }

  for (let candidate of attempts) {
    candidate = candidate
      .replace(/^```\s*(quiz|json)?/i, '')
      .replace(/```$/i, '')
      .replace(/[“”]/g, '"')
      .replace(/[‘’]/g, "'")
      .replace(/,\s*([}\]])/g, '$1')
      .trim();
    try {
      const payload = JSON.parse(candidate);
      if (payload?.type !== 'interactive_quiz' || !Array.isArray(payload.questions)) continue;
      const seenQuestions = new Set();
      const questions = payload.questions
        .map(q => ({
          question: String(q.question || '').trim(),
          options: q.options || {},
          correct: String(q.correct || '').trim().toUpperCase().slice(0, 1),
          explanation: String(q.explanation || '').trim(),
        }))
        .filter(q => q.question && ['A', 'B', 'C', 'D'].includes(q.correct))
        .filter(q => {
          const key = normalizeString(q.question).replace(/\s+/g, ' ').trim();
          if (seenQuestions.has(key)) return false;
          seenQuestions.add(key);
          return true;
        });
      if (!questions.length) return null;
      return {
        type: 'interactive_quiz',
        title: String(payload.title || 'Questionário interativo').trim(),
        show_answers: Boolean(payload.show_answers),
        questions,
      };
    } catch (err) {
      // tenta próximo formato
    }
  }
  console.warn('[QUIZ][PARSE][ERRO] Não consegui converter o bloco em quiz interativo.');
  return null;
}

function renderInteractiveQuiz(quiz) {
  const id = `quiz-${Math.random().toString(16).slice(2)}`;
  const showAnswers = Boolean(quiz.show_answers);
  const documentIds = (() => {
    try {
      const checked = typeof getSelectedDocumentIds === 'function' ? getSelectedDocumentIds() : [];
      return checked.length ? checked : (state.selectedDocumentIds || []);
    } catch {
      return state.selectedDocumentIds || [];
    }
  })();
  const questionsHtml = quiz.questions.map((q, index) => {
    const qid = `${id}-q${index}`;
    const options = ['A', 'B', 'C', 'D'].map(label => {
      const text = q.options?.[label] || '';
      const answerClass = showAnswers && label === q.correct ? ' correct' : '';
      const disabled = showAnswers ? 'disabled' : '';
      return `
        <label class="quiz-option${answerClass}" data-option-label="${label}">
          <input type="radio" name="${qid}" value="${label}" ${disabled}>
          <span class="quiz-letter">${label}</span>
          <span>${escapeHtml(text)}</span>
        </label>`;
    }).join('');
    const initialFeedback = showAnswers
      ? `<div class="quiz-feedback visible" aria-live="polite">✅ Resposta correta: <strong>${escapeHtml(q.correct)}</strong>. ${escapeHtml(q.explanation)}</div>`
      : '<div class="quiz-feedback" aria-live="polite"></div>';
    return `
      <div class="quiz-question" data-correct="${escapeHtml(q.correct)}" data-explanation="${escapeHtml(q.explanation)}" data-question="${escapeHtml(q.question)}">
        <div class="quiz-q-title"><span>${index + 1}</span>${escapeHtml(q.question)}</div>
        <div class="quiz-options">${options}</div>
        ${initialFeedback}
      </div>`;
  }).join('');

  const answerNote = showAnswers
    ? '<p class="quiz-note">Gabarito liberado porque foi solicitado no pedido.</p>'
    : '<p class="quiz-note">As respostas ficam ocultas até você clicar em corrigir ou em Ver gabarito.</p>';
  const answerClass = showAnswers ? ' show-answers answers-revealed' : '';

  return `
    <section class="material-card quiz quiz-form-card${answerClass}" id="${id}" data-quiz-title="${escapeHtml(quiz.title)}" data-document-ids="${escapeHtml(JSON.stringify(documentIds))}">
      <div class="material-head">
        <span class="material-icon">▦</span>
        <strong>${escapeHtml(quiz.title)}</strong>
      </div>
      ${answerNote}
      <div class="quiz-form">${questionsHtml}</div>
      <div class="quiz-actions">
        <button type="button" class="quiz-submit" data-quiz-submit ${showAnswers ? 'disabled' : ''}>${showAnswers ? 'Gabarito aberto' : 'Corrigir'}</button>
        <button type="button" class="quiz-answer" data-quiz-answer ${showAnswers ? 'disabled' : ''}>Ver gabarito</button>
        <button type="button" class="quiz-reset" data-quiz-reset>Refazer</button>
      </div>
      <div class="quiz-score" aria-live="polite"></div>
    </section>`;
}

function collectQuizAnswers(card) {
  const questions = [...card.querySelectorAll('.quiz-question')];
  return questions.map((question, index) => {
    const correct = question.dataset.correct || '';
    const selected = question.querySelector('input[type="radio"]:checked')?.value || '';
    return {
      index: index + 1,
      question: question.dataset.question || question.querySelector('.quiz-q-title')?.innerText || '',
      selected,
      correct,
      is_correct: Boolean(selected && selected === correct),
    };
  });
}

async function saveQuizAttempt(card, score, total, answered, answers) {
  try {
    const documentIds = JSON.parse(card.dataset.documentIds || '[]');
    await api('/chat/quiz-attempt', {
      method: 'POST',
      body: JSON.stringify({
        notebook_id: state.notebookId,
        document_ids: Array.isArray(documentIds) ? documentIds : [],
        title: card.dataset.quizTitle || 'Questionário',
        score,
        total_questions: total,
        answered,
        answers,
      }),
    });
    console.log('[QUIZ] Pontuação salva no banco:', { score, total, answered });
  } catch (err) {
    console.error('[QUIZ][SAVE][ERRO] Não foi possível salvar pontuação:', err);
  }
}

function gradeQuizCard(card) {
  if (card.classList.contains('graded')) return;
  const questions = [...card.querySelectorAll('.quiz-question')];
  let score = 0;
  let answered = 0;
  questions.forEach(question => {
    const correct = question.dataset.correct;
    const selected = question.querySelector('input[type="radio"]:checked')?.value || '';
    const feedback = question.querySelector('.quiz-feedback');
    const explanation = question.dataset.explanation || '';
    question.querySelectorAll('.quiz-option').forEach(option => {
      const label = option.dataset.optionLabel;
      option.classList.remove('correct', 'wrong', 'chosen-correct', 'chosen-wrong');
      if (label === correct) option.classList.add('correct');
      if (selected && label === selected) option.classList.add(selected === correct ? 'chosen-correct' : 'chosen-wrong');
      if (selected && label === selected && selected !== correct) option.classList.add('wrong');
    });
    if (selected) answered += 1;
    if (selected === correct) score += 1;
    feedback.classList.add('visible');
    if (!selected) {
      feedback.innerHTML = '⚠️ Selecione uma alternativa.';
    } else if (selected === correct) {
      feedback.innerHTML = `✅ Correto. ${escapeHtml(explanation)}`;
    } else {
      feedback.innerHTML = `❌ Incorreto. Resposta correta: <strong>${escapeHtml(correct)}</strong>. ${escapeHtml(explanation)}`;
    }
  });
  const scoreBox = card.querySelector('.quiz-score');
  scoreBox.innerHTML = `<strong>Resultado:</strong> ${score}/${questions.length} acertos (${answered}/${questions.length} respondidas).`;
  card.classList.add('graded');
  card.querySelectorAll('input[type="radio"]').forEach(input => (input.disabled = true));
  const submit = card.querySelector('[data-quiz-submit]');
  if (submit) {
    submit.disabled = true;
    submit.textContent = 'Corrigido';
  }
  const answers = collectQuizAnswers(card);
  saveQuizAttempt(card, score, questions.length, answered, answers);
}

function revealQuizAnswers(card) {
  if (card.classList.contains('graded')) return;
  card.classList.add('answers-revealed');
  card.querySelectorAll('.quiz-question').forEach(question => {
    const correct = question.dataset.correct;
    const explanation = question.dataset.explanation || '';
    const feedback = question.querySelector('.quiz-feedback');
    question.querySelectorAll('.quiz-option').forEach(option => {
      option.classList.remove('wrong', 'chosen-correct', 'chosen-wrong');
      if (option.dataset.optionLabel === correct) option.classList.add('correct');
    });
    feedback.classList.add('visible');
    feedback.innerHTML = `✅ Resposta correta: <strong>${escapeHtml(correct)}</strong>. ${escapeHtml(explanation)}`;
  });
  const answerBtn = card.querySelector('[data-quiz-answer]');
  if (answerBtn) {
    answerBtn.disabled = true;
    answerBtn.textContent = 'Gabarito aberto';
  }
}

function resetQuizCard(card) {
  card.querySelectorAll('input[type="radio"]').forEach(input => {
    input.checked = false;
    input.disabled = false;
  });
  card.querySelectorAll('.quiz-option').forEach(option => option.classList.remove('selected', 'correct', 'wrong', 'chosen-correct', 'chosen-wrong'));
  card.querySelectorAll('.quiz-feedback').forEach(feedback => {
    feedback.innerHTML = '';
    feedback.classList.remove('visible');
  });
  const scoreBox = card.querySelector('.quiz-score');
  if (scoreBox) scoreBox.innerHTML = '';
  card.classList.remove('graded', 'answers-revealed');
  const submit = card.querySelector('[data-quiz-submit]');
  if (submit) {
    submit.disabled = false;
    submit.textContent = 'Corrigir';
  }
  const answerBtn = card.querySelector('[data-quiz-answer]');
  if (answerBtn) {
    answerBtn.disabled = false;
    answerBtn.textContent = 'Ver gabarito';
  }
}

function renderMermaidCard(code) {
  const id = `mermaid-${Math.random().toString(16).slice(2)}`;
  const raw = String(code || '').trim();
  return `
    <section class="material-card flowchart mermaid-wrap">
      <div class="material-head">
        <span class="material-icon">▤</span>
        <strong>Fluxograma</strong>
        <button class="copy-btn" data-label="Copiar" data-copy-target="#${id}-code" type="button">Copiar</button>
      </div>
      <div class="mermaid-stage">
        <pre id="${id}" class="mermaid" data-raw="${escapeHtml(raw)}">${escapeHtml(raw)}</pre>
      </div>
      <pre id="${id}-code" class="mermaid-code" data-raw="${escapeHtml(raw)}">${escapeHtml(raw)}</pre>
    </section>`;
}

function inlineMarkdown(html) {
  return html
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/^\s*[-*]\s+(.+)$/gm, '• $1');
}

function normalizeString(str) {
  return String(str || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

function escapeHtml(str) {
  return String(str).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function renderMermaidBlocks() {
  if (!window.mermaid) {
    console.warn('[MERMAID] Biblioteca não carregada.');
    return;
  }
  try {
    window.mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' });
    await window.mermaid.run({ querySelector: '.mermaid' });
  } catch (e) {
    console.warn('[MERMAID][ERRO]', e);
  }
}
