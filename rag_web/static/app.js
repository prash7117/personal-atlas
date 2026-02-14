/*
 * Copyright (c) 2026 Prashanth Shankar Narayan
 * SPDX-License-Identifier: Apache-2.0
 */

const qs = (sel) => document.querySelector(sel);
const qsa = (sel) => Array.from(document.querySelectorAll(sel));

const DISPLAY_NAME_MAX = 80;
const REPO_ID_MAX = 80;
const REPO_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.\- ]*$/;
const DEFAULT_REPO_ID = 'default';

const state = {
  repos: [],
  health: null,
  eventSource: null,
  editingRepoId: null,
  repoGroups: [],
  selectedRepoIds: new Set(),
  selectedRepoGroups: new Set(),
  allRepos: true,
  repoFilter: '',
  ingestRepoMode: 'existing',
  createdRepoId: null,
  repoCreateIdTouched: false,
  ingestNewRepoIdTouched: false,
  ingestSelectedRepoIds: new Set(),
  ingestSelectedRepoGroups: new Set(),
  ingestRepoFilter: '',
  debugRepoId: '',
  debugFileKey: '',
  debugFilesRepoId: '',
  debugFiles: [],
  allowedIngestRoots: [],
  openaiApiKeySet: false,
  openaiApiKeyVerified: false,
  openaiApiKeySource: 'missing',
};

function setActiveTab(name) {
  qsa('.tab').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
  qsa('.pane').forEach((pane) => {
    pane.classList.toggle('active', pane.id === `tab-${name}`);
  });
  if (name === 'ingest') {
    updateIngestButtonState();
  }
  if (name === 'ask') {
    updateAskButtonState();
  }
  if (name === 'debug') {
    if (state.debugRepoId && state.debugFilesRepoId !== state.debugRepoId) {
      loadDebugFiles(state.debugRepoId);
    }
    updateDebugLoadButtonState();
  }
}

function formatTime(ts) {
  if (!ts) return '—';
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString();
}

async function fetchJSON(url, options) {
  const resp = await fetch(url, options);
  const data = await resp.json();
  if (!resp.ok) {
    const msg = data && data.detail ? JSON.stringify(data.detail) : resp.statusText;
    throw new Error(msg);
  }
  return data;
}

function displayNameFor(repo) {
  const raw = (repo && (repo.display_name || repo.repo_id)) || '';
  return raw.trim();
}

function isOpenAIConfigured() {
  return Boolean(state.openaiApiKeySet && state.openaiApiKeyVerified);
}

function setSettingsMessage(text, isError) {
  const el = qs('#settings-openai-message');
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('error', Boolean(isError));
}

function setSettingsGateMessage(text, isError) {
  const el = qs('#settings-gate-message');
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('error', Boolean(isError));
}

function setSettingsGateVisible(visible) {
  const gate = qs('#settings-first-run');
  if (!gate) return;
  gate.classList.toggle('hidden', !visible);
  document.body.classList.toggle('settings-gate-open', visible);
}

function refreshOpenAIAccess() {
  const ready = isOpenAIConfigured();
  setSettingsGateVisible(!ready);
  if (!ready) {
    setActiveTab('settings');
  }
  updateAskButtonState();
  updateIngestButtonState();
}

function updateSettingsStatusLine(testPayload) {
  const statusEl = qs('#settings-openai-status');
  if (!statusEl) return;

  statusEl.classList.toggle('missing', !isOpenAIConfigured());
  if (!state.openaiApiKeySet) {
    statusEl.textContent = 'OpenAI API key is not configured.';
    return;
  }
  if (!state.openaiApiKeyVerified) {
    statusEl.textContent =
      'OpenAI API key is configured, but connection is not verified yet.';
    return;
  }

  const embedModel =
    testPayload && testPayload.embed_model
      ? `embed=${testPayload.embed_model}`
      : '';
  const chatModel =
    testPayload && testPayload.chat_model ? `chat=${testPayload.chat_model}` : '';
  const modelInfo = [embedModel, chatModel].filter((value) => value).join(' • ');
  if (modelInfo) {
    statusEl.textContent = `OpenAI connection verified (${modelInfo}).`;
  } else {
    statusEl.textContent = 'OpenAI connection verified.';
  }
}

function updateSettingsStatusUi(payload) {
  const clearBtn = qs('#settings-openai-clear');

  const configured = Boolean(payload && payload.openai_api_key_set);
  const source = (payload && payload.source) || 'missing';
  const canClear = Boolean(payload && payload.can_clear);
  const allowedRoots =
    payload && Array.isArray(payload.allowed_ingest_roots)
      ? payload.allowed_ingest_roots.filter((root) => root)
      : [];

  state.openaiApiKeySet = configured;
  state.openaiApiKeySource = source;
  state.openaiApiKeyVerified = false;
  state.allowedIngestRoots = allowedRoots;

  if (clearBtn) {
    clearBtn.disabled = !canClear;
    clearBtn.title = canClear
      ? 'Remove key saved in settings'
      : 'No saved settings key to clear';
  }

  updateSettingsStatusLine();
  fillPathSuggestions();
  refreshOpenAIAccess();
}

async function testOpenAIConnection(options) {
  const useInput = Boolean(options && options.useInput);
  const silent = Boolean(options && options.silent);
  const settingsInput = qs('#settings-openai-key');
  const gateInput = qs('#settings-gate-key');
  let candidate = '';

  if (useInput) {
    candidate = (settingsInput && settingsInput.value.trim()) || '';
    if (!candidate) {
      candidate = (gateInput && gateInput.value.trim()) || '';
    }
  }

  if (!silent) {
    setSettingsMessage('Testing OpenAI connection...', false);
    setSettingsGateMessage('Testing OpenAI connection...', false);
  }

  const statusEl = qs('#settings-openai-status');
  if (statusEl && state.openaiApiKeySet) {
    statusEl.classList.remove('missing');
    statusEl.textContent = 'Testing OpenAI connection...';
  }

  const body = {};
  if (candidate) {
    body.api_key = candidate;
  }

  try {
    const payload = await fetchJSON('/api/settings/openai-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    state.openaiApiKeyVerified = true;
    updateSettingsStatusLine(payload);
    refreshOpenAIAccess();

    if (!state.openaiApiKeySet && candidate) {
      setSettingsMessage(
        'Connection test passed. Save the key to enable Ask and Ingest.',
        false
      );
      setSettingsGateMessage(
        'Connection test passed. Save the key to continue.',
        false
      );
    } else if (!silent) {
      setSettingsMessage('OpenAI connection test passed.', false);
      setSettingsGateMessage('', false);
    }
    return payload;
  } catch (err) {
    state.openaiApiKeyVerified = false;
    updateSettingsStatusLine();
    refreshOpenAIAccess();
    const message = `Connection test failed: ${err.message}`;
    setSettingsMessage(message, true);
    setSettingsGateMessage(message, true);
    return null;
  }
}

async function loadSettings() {
  try {
    const payload = await fetchJSON('/api/settings');
    updateSettingsStatusUi(payload);
    if (state.openaiApiKeySet) {
      await testOpenAIConnection({ useInput: false, silent: true });
    } else {
      setSettingsMessage('', false);
      setSettingsGateMessage('', false);
    }
    return payload;
  } catch (err) {
    state.openaiApiKeySet = false;
    state.openaiApiKeyVerified = false;
    state.openaiApiKeySource = 'missing';
    const statusEl = qs('#settings-openai-status');
    if (statusEl) {
      statusEl.classList.add('missing');
      statusEl.textContent = `Settings unavailable: ${err.message}`;
    }
    refreshOpenAIAccess();
    setSettingsMessage(`Error loading settings: ${err.message}`, true);
    setSettingsGateMessage(`Error loading settings: ${err.message}`, true);
    return null;
  }
}

async function saveOpenAIKey(rawValue) {
  const apiKey = (rawValue || '').trim();
  if (!apiKey) {
    setSettingsMessage('OpenAI API key is required.', true);
    setSettingsGateMessage('OpenAI API key is required.', true);
    return;
  }

  setSettingsMessage('Saving key...', false);
  setSettingsGateMessage('Saving key...', false);
  try {
    const payload = await fetchJSON('/api/settings/openai-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    });
    const field = qs('#settings-openai-key');
    const gateField = qs('#settings-gate-key');
    if (field) field.value = '';
    if (gateField) gateField.value = '';
    updateSettingsStatusUi(payload);
    await testOpenAIConnection({ useInput: false, silent: false });
  } catch (err) {
    setSettingsMessage(`Save failed: ${err.message}`, true);
    setSettingsGateMessage(`Save failed: ${err.message}`, true);
  }
}

async function clearOpenAIKey() {
  setSettingsMessage('Clearing saved key...', false);
  try {
    const payload = await fetchJSON('/api/settings/openai-key', {
      method: 'DELETE',
    });
    updateSettingsStatusUi(payload);
    if (payload.source === 'environment' && payload.openai_api_key_set) {
      await testOpenAIConnection({ useInput: false, silent: false });
      setSettingsMessage('Saved key cleared. Environment key is active.', false);
      return;
    }
    setSettingsMessage('Saved OpenAI API key cleared.', false);
    setSettingsGateMessage('OpenAI API key is required to continue.', true);
  } catch (err) {
    setSettingsMessage(`Clear failed: ${err.message}`, true);
  }
}

function updateRepoSummary() {
  const summary = qs('#repo-select-summary');
  if (!summary) return;
  if (state.allRepos) {
    summary.textContent = 'All repos';
    return;
  }
  const repoCount = state.selectedRepoIds.size;
  const groupCount = state.selectedRepoGroups.size;
  if (!repoCount && !groupCount) {
    summary.textContent = 'All repos';
    return;
  }
  const parts = [];
  if (repoCount) {
    parts.push(`${repoCount} repo${repoCount === 1 ? '' : 's'}`);
  }
  if (groupCount) {
    parts.push(`${groupCount} group${groupCount === 1 ? '' : 's'}`);
  }
  summary.textContent = parts.join(' + ');
}

function updateIngestRepoSummary() {
  const summary = qs('#ingest-repo-summary');
  if (!summary) return;
  const repoCount = state.ingestSelectedRepoIds.size;
  const groupCount = state.ingestSelectedRepoGroups.size;
  if (!repoCount && !groupCount) {
    summary.textContent = 'Select repos';
    return;
  }
  if (repoCount === 1 && !groupCount) {
    const selectedRepoId = Array.from(state.ingestSelectedRepoIds)[0];
    const selectedRepo = state.repos.find((repo) => repo.repo_id === selectedRepoId);
    summary.textContent = selectedRepo ? displayNameFor(selectedRepo) : selectedRepoId;
    return;
  }
  const parts = [];
  if (repoCount) {
    parts.push(`${repoCount} repo${repoCount === 1 ? '' : 's'}`);
  }
  if (groupCount) {
    parts.push(`${groupCount} group${groupCount === 1 ? '' : 's'}`);
  }
  summary.textContent = parts.join(' + ');
}

function updateAskButtonState() {
  const btn = qs('#ask-submit');
  const question = qs('#ask-question');
  if (!btn || !question) return;
  const hasQuestion = Boolean(question.value.trim());
  const hasRepos =
    state.allRepos ||
    state.selectedRepoIds.size > 0 ||
    state.selectedRepoGroups.size > 0;
  btn.disabled = !(hasQuestion && hasRepos && isOpenAIConfigured());
}

function setAllRepos(enabled) {
  state.allRepos = enabled;
  if (enabled) {
    state.selectedRepoIds.clear();
    state.selectedRepoGroups.clear();
  }
  renderRepoSelector();
}

function renderRepoSelector() {
  const groupList = qs('#repo-groups-list');
  const repoList = qs('#repo-list');
  const groupEmpty = qs('#repo-groups-empty');
  const repoEmpty = qs('#repo-list-empty');
  const groupSection = qs('#ask-groups-section');
  const repoSection = qs('#ask-repos-section');
  const filterInput = qs('#repo-filter');
  const allToggle = qs('#ask-all-repos');
  if (!groupList || !repoList) return;

  if (filterInput) {
    filterInput.value = state.repoFilter;
  }
  if (allToggle) {
    allToggle.checked = state.allRepos;
  }
  if (groupSection) {
    groupSection.classList.toggle('disabled', state.allRepos);
    groupSection.setAttribute('aria-disabled', state.allRepos ? 'true' : 'false');
  }
  if (repoSection) {
    repoSection.classList.toggle('disabled', state.allRepos);
    repoSection.setAttribute('aria-disabled', state.allRepos ? 'true' : 'false');
  }

  const filter = state.repoFilter.trim().toLowerCase();
  groupList.innerHTML = '';
  repoList.innerHTML = '';

  const groups = state.repoGroups || [];
  let groupVisible = 0;
  groups.forEach((group) => {
    const name = group.name || '';
    if (!name) return;
    const hay = `${name}`.toLowerCase();
    if (filter && hay.indexOf(filter) === -1) {
      return;
    }
    groupVisible += 1;
    const label = document.createElement('label');
    label.className = 'select-item';
    label.title = name;
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.disabled = state.allRepos;
    checkbox.checked = state.selectedRepoGroups.has(name);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        state.selectedRepoGroups.add(name);
        state.allRepos = false;
      } else {
        state.selectedRepoGroups.delete(name);
        if (!state.selectedRepoIds.size && !state.selectedRepoGroups.size) {
          state.allRepos = true;
        }
      }
      renderRepoSelector();
    });
    const text = document.createElement('span');
    text.className = 'select-label';
    text.textContent = name;
    const meta = document.createElement('span');
    meta.className = 'select-meta';
    const repoCount = Array.isArray(group.repo_ids) ? group.repo_ids.length : 0;
    meta.textContent = repoCount ? `${repoCount} repos` : '0 repos';
    label.appendChild(checkbox);
    label.appendChild(text);
    label.appendChild(meta);
    groupList.appendChild(label);
  });

  if (groupEmpty) {
    groupEmpty.style.display = groupVisible ? 'none' : 'block';
  }

  let repoVisible = 0;
  state.repos.forEach((repo) => {
    const name = displayNameFor(repo);
    const repoId = repo.repo_id || '';
    if (!repoId) return;
    const hay = `${name} ${repoId}`.toLowerCase();
    if (filter && hay.indexOf(filter) === -1) {
      return;
    }
    repoVisible += 1;
    const label = document.createElement('label');
    label.className = 'select-item';
    label.title = repoId;
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.disabled = state.allRepos;
    checkbox.checked = state.selectedRepoIds.has(repoId);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        state.selectedRepoIds.add(repoId);
        state.allRepos = false;
      } else {
        state.selectedRepoIds.delete(repoId);
        if (!state.selectedRepoIds.size && !state.selectedRepoGroups.size) {
          state.allRepos = true;
        }
      }
      renderRepoSelector();
    });
    const text = document.createElement('span');
    text.className = 'select-label';
    text.textContent = name;
    const meta = document.createElement('span');
    meta.className = 'select-meta';
    meta.textContent = name && name !== repoId ? repoId : '';
    if (!meta.textContent) {
      meta.style.display = 'none';
    }
    label.appendChild(checkbox);
    label.appendChild(text);
    label.appendChild(meta);
    repoList.appendChild(label);
  });

  if (repoEmpty) {
    repoEmpty.style.display = repoVisible ? 'none' : 'block';
  }

  updateRepoSummary();
  updateAskButtonState();
}

function renderIngestRepoSelector() {
  const groupList = qs('#ingest-groups-list');
  const repoList = qs('#ingest-repo-list');
  const groupEmpty = qs('#ingest-groups-empty');
  const repoEmpty = qs('#ingest-repo-list-empty');
  const filterInput = qs('#ingest-repo-filter');
  if (!groupList || !repoList) return;

  if (filterInput) {
    filterInput.value = state.ingestRepoFilter;
  }

  const filter = state.ingestRepoFilter.trim().toLowerCase();
  groupList.innerHTML = '';
  repoList.innerHTML = '';

  const groups = state.repoGroups || [];
  let groupVisible = 0;
  groups.forEach((group) => {
    const name = group.name || '';
    if (!name) return;
    const hay = `${name}`.toLowerCase();
    if (filter && hay.indexOf(filter) === -1) {
      return;
    }
    groupVisible += 1;
    const label = document.createElement('label');
    label.className = 'select-item';
    label.title = name;
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = state.ingestSelectedRepoGroups.has(name);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        clearImplicitDefaultIngestSelection();
        state.ingestSelectedRepoGroups.add(name);
      } else {
        state.ingestSelectedRepoGroups.delete(name);
      }
      renderIngestRepoSelector();
    });
    const text = document.createElement('span');
    text.className = 'select-label';
    text.textContent = name;
    const meta = document.createElement('span');
    meta.className = 'select-meta';
    const repoCount = Array.isArray(group.repo_ids) ? group.repo_ids.length : 0;
    meta.textContent = repoCount ? `${repoCount} repos` : '0 repos';
    label.appendChild(checkbox);
    label.appendChild(text);
    label.appendChild(meta);
    groupList.appendChild(label);
  });

  if (groupEmpty) {
    groupEmpty.style.display = groupVisible ? 'none' : 'block';
  }

  let repoVisible = 0;
  state.repos.forEach((repo) => {
    const name = displayNameFor(repo);
    const repoId = repo.repo_id || '';
    if (!repoId) return;
    const hay = `${name} ${repoId}`.toLowerCase();
    if (filter && hay.indexOf(filter) === -1) {
      return;
    }
    repoVisible += 1;
    const label = document.createElement('label');
    label.className = 'select-item';
    label.title = repoId;
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = state.ingestSelectedRepoIds.has(repoId);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        if (repoId !== DEFAULT_REPO_ID) {
          clearImplicitDefaultIngestSelection();
        }
        state.ingestSelectedRepoIds.add(repoId);
      } else {
        state.ingestSelectedRepoIds.delete(repoId);
      }
      renderIngestRepoSelector();
    });
    const text = document.createElement('span');
    text.className = 'select-label';
    text.textContent = name;
    const meta = document.createElement('span');
    meta.className = 'select-meta';
    meta.textContent = name && name !== repoId ? repoId : '';
    if (!meta.textContent) {
      meta.style.display = 'none';
    }
    label.appendChild(checkbox);
    label.appendChild(text);
    label.appendChild(meta);
    repoList.appendChild(label);
  });

  if (repoEmpty) {
    repoEmpty.style.display = repoVisible ? 'none' : 'block';
  }

  updateIngestRepoSummary();
  updateIngestButtonState();
}

function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function linkifySegment(text) {
  if (!text) return '';
  const urlRegex = /https?:\/\/[^\s<]+/g;
  let result = '';
  let lastIndex = 0;
  let match = urlRegex.exec(text);
  while (match) {
    const urlStart = match.index;
    const urlText = match[0];
    result += escapeHtml(text.slice(lastIndex, urlStart));
    let url = urlText;
    let trailing = '';
    while (url && /[)\].,!?;:]+$/.test(url)) {
      trailing = url.slice(-1) + trailing;
      url = url.slice(0, -1);
    }
    if (url) {
      result += `<a href="${escapeAttr(url)}" target="_blank" rel="noopener">${escapeHtml(url)}</a>`;
    }
    result += escapeHtml(trailing);
    lastIndex = urlStart + urlText.length;
    match = urlRegex.exec(text);
  }
  result += escapeHtml(text.slice(lastIndex));
  return result;
}

function renderInline(text) {
  if (!text) return '';
  let output = '';
  let index = 0;
  while (index < text.length) {
    if (text[index] === '`') {
      const end = text.indexOf('`', index + 1);
      if (end === -1) {
        output += linkifySegment(text.slice(index));
        break;
      }
      const code = text.slice(index + 1, end);
      output += `<code>${escapeHtml(code)}</code>`;
      index = end + 1;
      continue;
    }
    if (text.startsWith('**', index)) {
      const end = text.indexOf('**', index + 2);
      if (end === -1) {
        output += linkifySegment(text.slice(index));
        break;
      }
      const bold = text.slice(index + 2, end);
      output += `<strong>${linkifySegment(bold)}</strong>`;
      index = end + 2;
      continue;
    }
    if (text[index] === '[') {
      const labelEnd = text.indexOf('](', index);
      if (labelEnd !== -1) {
        const urlEnd = text.indexOf(')', labelEnd + 2);
        if (urlEnd !== -1) {
          const label = text.slice(index + 1, labelEnd);
          const url = text.slice(labelEnd + 2, urlEnd).trim();
          if (/^https?:\/\//i.test(url)) {
            output += `<a href="${escapeAttr(url)}" target="_blank" rel="noopener">${renderInline(label)}</a>`;
            index = urlEnd + 1;
            continue;
          }
        }
      }
      output += escapeHtml(text[index]);
      index += 1;
      continue;
    }
    const nextCode = text.indexOf('`', index);
    const nextBold = text.indexOf('**', index);
    const nextLink = text.indexOf('[', index);
    let next = -1;
    if (nextCode !== -1) next = nextCode;
    if (nextBold !== -1 && (next === -1 || nextBold < next)) next = nextBold;
    if (nextLink !== -1 && (next === -1 || nextLink < next)) next = nextLink;
    if (next === -1) {
      output += linkifySegment(text.slice(index));
      break;
    }
    output += linkifySegment(text.slice(index, next));
    index = next;
  }
  return output;
}

function renderMarkdown(text) {
  if (!text) return '';
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let html = '';
  let inCode = false;
  let codeLang = '';
  let codeLines = [];
  let inUl = false;
  let inOl = false;
  let paraLines = [];

  const flushParagraph = () => {
    if (!paraLines.length) return;
    const joined = paraLines.join(' ').trim();
    paraLines = [];
    if (joined) {
      html += `<p>${renderInline(joined)}</p>`;
    }
  };

  const closeLists = () => {
    if (inUl) {
      html += '</ul>';
      inUl = false;
    }
    if (inOl) {
      html += '</ol>';
      inOl = false;
    }
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (inCode) {
      if (trimmed.startsWith('```')) {
        const lang = codeLang ? ` class="language-${escapeAttr(codeLang)}"` : '';
        html += `<pre><code${lang}>${escapeHtml(codeLines.join('\n'))}</code></pre>`;
        inCode = false;
        codeLang = '';
        codeLines = [];
      } else {
        codeLines.push(line);
      }
      return;
    }

    if (trimmed.startsWith('```')) {
      flushParagraph();
      closeLists();
      inCode = true;
      codeLang = trimmed.slice(3).trim();
      codeLines = [];
      return;
    }

    if (!trimmed) {
      flushParagraph();
      closeLists();
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      closeLists();
      const level = headingMatch[1].length;
      const tag = level === 1 ? 'h2' : level === 2 ? 'h3' : 'h4';
      html += `<${tag}>${renderInline(headingMatch[2].trim())}</${tag}>`;
      return;
    }

    if (trimmed.endsWith(':') && trimmed.length <= 60) {
      flushParagraph();
      closeLists();
      html += `<h3>${renderInline(trimmed.slice(0, -1))}</h3>`;
      return;
    }

    const ulMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (ulMatch || olMatch) {
      flushParagraph();
      if (ulMatch) {
        if (inOl) {
          html += '</ol>';
          inOl = false;
        }
        if (!inUl) {
          html += '<ul>';
          inUl = true;
        }
        html += `<li>${renderInline(ulMatch[1])}</li>`;
      } else if (olMatch) {
        if (inUl) {
          html += '</ul>';
          inUl = false;
        }
        if (!inOl) {
          html += '<ol>';
          inOl = true;
        }
        html += `<li>${renderInline(olMatch[1])}</li>`;
      }
      return;
    }

    paraLines.push(trimmed);
  });

  if (inCode) {
    const lang = codeLang ? ` class="language-${escapeAttr(codeLang)}"` : '';
    html += `<pre><code${lang}>${escapeHtml(codeLines.join('\n'))}</code></pre>`;
  }
  flushParagraph();
  closeLists();

  return html;
}

function collectRoots(repo) {
  if (!repo) return [];
  if (Array.isArray(repo.roots) && repo.roots.length) {
    return repo.roots.filter((root) => root);
  }
  if (repo.root) return [repo.root];
  return [];
}

function renderRootCell(cell, repo) {
  const roots = collectRoots(repo);
  cell.innerHTML = '';
  if (!roots.length) {
    cell.textContent = '—';
    return;
  }
  cell.classList.add('roots-cell');
  const primary = document.createElement('div');
  primary.className = 'root-primary';
  primary.textContent = roots[0];
  primary.title = roots.join('\n');
  cell.appendChild(primary);

  if (roots.length > 1) {
    const more = document.createElement('div');
    more.className = 'root-more';
    more.textContent = `+${roots.length - 1} more`;
    cell.appendChild(more);
  }
}

function showRepoCreatePanel(show) {
  const panel = qs('#repo-create');
  const success = qs('#repo-create-success');
  if (!panel) return;
  panel.classList.toggle('hidden', !show);
  if (show) {
    state.createdRepoId = null;
    if (success) {
      success.classList.add('hidden');
    }
    const nameInput = qs('#repo-create-name');
    if (nameInput) {
      setTimeout(() => {
        nameInput.focus();
      }, 0);
    }
  }
}

function resetRepoCreateForm() {
  const nameInput = qs('#repo-create-name');
  const idInput = qs('#repo-create-id');
  const errorEl = qs('#repo-create-error');
  const saveBtn = qs('#repo-create-save');
  if (nameInput) nameInput.value = '';
  if (idInput) idInput.value = '';
  if (errorEl) errorEl.textContent = '';
  state.repoCreateIdTouched = false;
  if (saveBtn) saveBtn.disabled = true;
}

function deriveRepoIdFromName(name) {
  const trimmed = (name || '').trim();
  if (!trimmed) return '';
  let repoId = trimmed.replace(/\s+/g, '_');
  repoId = repoId.replace(/[^A-Za-z0-9_.-]/g, '_');
  repoId = repoId.replace(/_+/g, '_');
  if (repoId.length > REPO_ID_MAX) {
    repoId = repoId.slice(0, REPO_ID_MAX);
  }
  return repoId;
}

function validateRepoCreate(name, repoId) {
  const trimmedName = (name || '').trim();
  if (!trimmedName) return 'Repo name is required.';
  if (trimmedName.indexOf('::') !== -1) return 'Repo name cannot contain "::".';
  if (trimmedName.length > DISPLAY_NAME_MAX) {
    return `Repo name must be ${DISPLAY_NAME_MAX} characters or fewer.`;
  }

  const trimmedId = (repoId || '').trim();
  if (!trimmedId) return 'Repo ID is required.';
  if (trimmedId.indexOf('::') !== -1) return 'Repo ID cannot contain "::".';
  if (trimmedId.length > REPO_ID_MAX) {
    return `Repo ID must be ${REPO_ID_MAX} characters or fewer.`;
  }
  if (!REPO_ID_RE.test(trimmedId)) {
    return 'Repo ID can only use letters, numbers, spaces, dot, dash, or underscore.';
  }

  const idLower = trimmedId.toLowerCase();
  const nameLower = trimmedName.toLowerCase();
  const conflictId = state.repos.find(
    (repo) => (repo.repo_id || '').toLowerCase() === idLower
  );
  if (conflictId) return 'Repo ID already exists.';
  const conflictName = state.repos.find((repo) => {
    const current = displayNameFor(repo).toLowerCase();
    return current === nameLower;
  });
  if (conflictName) return 'Repo name already exists.';
  return '';
}

function syncRepoCreateIdFromName() {
  const nameInput = qs('#repo-create-name');
  const idInput = qs('#repo-create-id');
  if (!nameInput || !idInput) return;
  if (!state.repoCreateIdTouched) {
    idInput.value = deriveRepoIdFromName(nameInput.value);
  }
}

function updateRepoCreateState() {
  const nameInput = qs('#repo-create-name');
  const idInput = qs('#repo-create-id');
  const errorEl = qs('#repo-create-error');
  const saveBtn = qs('#repo-create-save');
  if (!nameInput || !idInput) return;
  const nameValue = nameInput.value.trim();
  const idValue = idInput.value.trim();
  const msg = validateRepoCreate(nameValue, idValue);
  if (errorEl) {
    errorEl.textContent = nameValue || idValue ? msg : '';
  }
  if (saveBtn) saveBtn.disabled = Boolean(msg);
}

function updateIngestButtonState() {
  const btn = qs('#ingest-submit');
  const pathInput = qs('#ingest-path');
  if (!btn || !pathInput) return;
  const hasPath = Boolean(pathInput.value.trim());
  let enabled = false;

  if (state.ingestRepoMode === 'new') {
    const nameValue = getIngestNewRepoName();
    const idValue = getIngestRepoId();
    const msg = validateRepoCreate(nameValue, idValue);
    enabled = hasPath && !msg;
  } else {
    const hasSelection =
      state.ingestSelectedRepoIds.size > 0 ||
      state.ingestSelectedRepoGroups.size > 0;
    const hasRepos = state.repos.length > 0;
    enabled = hasSelection && hasRepos;
  }

  if (!isOpenAIConfigured()) {
    enabled = false;
  }

  btn.disabled = !enabled;
}

function ensureIngestDefaultSelection(knownIds) {
  const ids =
    knownIds ||
    new Set(state.repos.map((repo) => repo.repo_id).filter((repoId) => repoId));
  if (
    state.ingestSelectedRepoIds.size > 0 ||
    state.ingestSelectedRepoGroups.size > 0
  ) {
    return;
  }
  if (ids.has(DEFAULT_REPO_ID)) {
    state.ingestSelectedRepoIds.add(DEFAULT_REPO_ID);
    return;
  }
  const firstRepo = state.repos.find((repo) => repo.repo_id);
  if (firstRepo && firstRepo.repo_id) {
    state.ingestSelectedRepoIds.add(firstRepo.repo_id);
  }
}

function clearImplicitDefaultIngestSelection() {
  if (
    state.ingestSelectedRepoGroups.size === 0 &&
    state.ingestSelectedRepoIds.size === 1 &&
    state.ingestSelectedRepoIds.has(DEFAULT_REPO_ID)
  ) {
    state.ingestSelectedRepoIds.delete(DEFAULT_REPO_ID);
  }
}

function syncIngestNewRepoIdFromName() {
  const nameInput = qs('#ingest-repo-new-name');
  const idInput = qs('#ingest-repo-new-id');
  if (!nameInput || !idInput) return;
  if (!state.ingestNewRepoIdTouched) {
    idInput.value = deriveRepoIdFromName(nameInput.value);
  }
}

function updateIngestNewRepoState() {
  const nameInput = qs('#ingest-repo-new-name');
  const idInput = qs('#ingest-repo-new-id');
  const errorEl = qs('#ingest-repo-new-error');
  if (!nameInput || !idInput) return;
  const nameValue = nameInput.value.trim();
  const idValue = idInput.value.trim();
  const msg = validateRepoCreate(nameValue, idValue);
  if (errorEl) {
    errorEl.textContent = nameValue || idValue ? msg : '';
  }
  updateIngestButtonState();
}

function setDebugStatus(text) {
  const status = qs('#debug-status');
  if (!status) return;
  status.textContent = text;
}

function clearDebugChunks(message) {
  const list = qs('#debug-chunks-list');
  const empty = qs('#debug-chunks-empty');
  if (list) {
    list.innerHTML = '';
  }
  if (empty) {
    empty.textContent = message || 'Select a file and load chunks.';
    empty.style.display = 'block';
  }
}

function getSelectedDebugFile() {
  if (!state.debugFileKey) return null;
  return (
    state.debugFiles.find((item) => item.relpath_key === state.debugFileKey) || null
  );
}

function updateDebugFileMeta() {
  const meta = qs('#debug-file-meta');
  if (!meta) return;
  const file = getSelectedDebugFile();
  if (!file) {
    if (!state.debugRepoId) {
      meta.textContent = 'Select a repo to view files.';
    } else {
      meta.textContent = 'Select a file to inspect chunks.';
    }
    return;
  }
  const chunkCount = Number(file.num_chunks || 0);
  meta.textContent = `${file.display_path || file.relpath} • ${chunkCount} chunk${chunkCount === 1 ? '' : 's'}`;
}

function updateDebugLoadButtonState() {
  const button = qs('#debug-load');
  if (!button) return;
  button.disabled = !(state.debugRepoId && state.debugFileKey);
}

function renderDebugFileSelector() {
  const select = qs('#debug-file');
  if (!select) return;
  select.innerHTML = '';

  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = state.debugRepoId
    ? 'Select a file...'
    : 'Select a repo first...';
  placeholder.disabled = true;
  select.appendChild(placeholder);

  const files = state.debugFiles || [];
  files.forEach((file) => {
    const option = document.createElement('option');
    option.value = file.relpath_key || '';
    const chunkCount = Number(file.num_chunks || 0);
    option.textContent = `${file.relpath || file.display_path || file.relpath_key} (${chunkCount})`;
    select.appendChild(option);
  });

  const hasSelectedFile = files.some(
    (file) => file.relpath_key === state.debugFileKey
  );
  if (!hasSelectedFile) {
    state.debugFileKey = '';
  }
  if (state.debugFileKey) {
    select.value = state.debugFileKey;
  } else {
    select.value = '';
  }

  updateDebugFileMeta();
  updateDebugLoadButtonState();
}

function renderDebugRepoSelector() {
  const select = qs('#debug-repo');
  if (!select) return;

  const knownIds = state.repos
    .map((repo) => repo.repo_id)
    .filter((repoId) => repoId);
  if (state.debugRepoId && knownIds.indexOf(state.debugRepoId) === -1) {
    state.debugRepoId = '';
    state.debugFiles = [];
    state.debugFilesRepoId = '';
    state.debugFileKey = '';
  }
  if (!state.debugRepoId && knownIds.length) {
    state.debugRepoId = knownIds[0];
  }

  select.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Select a repo...';
  placeholder.disabled = true;
  select.appendChild(placeholder);

  state.repos.forEach((repo) => {
    const repoId = repo.repo_id || '';
    if (!repoId) return;
    const option = document.createElement('option');
    option.value = repoId;
    option.textContent = displayNameFor(repo);
    select.appendChild(option);
  });

  if (state.debugRepoId) {
    select.value = state.debugRepoId;
  } else {
    select.value = '';
  }

  if (!state.debugRepoId) {
    state.debugFiles = [];
    state.debugFilesRepoId = '';
    state.debugFileKey = '';
    renderDebugFileSelector();
    setDebugStatus('Idle');
    clearDebugChunks('No repos available.');
    return;
  }

  if (state.debugFilesRepoId !== state.debugRepoId) {
    loadDebugFiles(state.debugRepoId);
    return;
  }

  renderDebugFileSelector();
}

async function loadDebugFiles(repoId) {
  if (!repoId) {
    state.debugFiles = [];
    state.debugFilesRepoId = '';
    state.debugFileKey = '';
    renderDebugFileSelector();
    return;
  }

  setDebugStatus('Loading files...');
  state.debugFiles = [];
  state.debugFilesRepoId = '';
  state.debugFileKey = '';
  renderDebugFileSelector();
  clearDebugChunks('Select a file and load chunks.');

  try {
    const data = await fetchJSON(`/api/debug/files/${encodeURIComponent(repoId)}`);
    if (state.debugRepoId !== repoId) {
      return;
    }
    state.debugFiles = Array.isArray(data.files) ? data.files : [];
    state.debugFilesRepoId = repoId;

    if (state.debugFiles.length) {
      state.debugFileKey = state.debugFiles[0].relpath_key || '';
      setDebugStatus('Ready');
    } else {
      state.debugFileKey = '';
      setDebugStatus('No files');
      clearDebugChunks('No chunked files found for this repo.');
    }
    renderDebugFileSelector();
  } catch (err) {
    if (state.debugRepoId !== repoId) {
      return;
    }
    state.debugFiles = [];
    state.debugFilesRepoId = repoId;
    state.debugFileKey = '';
    renderDebugFileSelector();
    setDebugStatus('Error');
    clearDebugChunks(`Error loading files: ${err.message}`);
  }
}

function renderDebugChunks(data) {
  const list = qs('#debug-chunks-list');
  const empty = qs('#debug-chunks-empty');
  if (!list || !empty) return;

  list.innerHTML = '';
  const chunks = Array.isArray(data.chunks) ? data.chunks : [];
  if (!chunks.length) {
    empty.textContent = 'No chunks found for this file.';
    empty.style.display = 'block';
    return;
  }

  empty.style.display = 'none';
  chunks.forEach((chunk) => {
    const item = document.createElement('div');
    item.className = 'debug-chunk-item';

    const head = document.createElement('div');
    head.className = 'debug-chunk-head';

    const title = document.createElement('strong');
    title.textContent = `chunk ${chunk.chunk_id}`;
    head.appendChild(title);

    const meta = document.createElement('span');
    meta.className = 'debug-chunk-meta';
    if (chunk.missing) {
      meta.textContent = 'missing in Qdrant';
      meta.classList.add('missing');
    } else {
      const text = typeof chunk.text === 'string' ? chunk.text : '';
      meta.textContent = `${text.length} chars`;
    }
    head.appendChild(meta);

    const text = document.createElement('pre');
    text.className = 'debug-chunk-text';
    text.textContent = chunk.missing ? '' : (chunk.text || '');

    item.appendChild(head);
    item.appendChild(text);
    list.appendChild(item);
  });
}

async function loadDebugChunks() {
  const repoId = state.debugRepoId;
  const relpathKey = state.debugFileKey;
  if (!repoId || !relpathKey) {
    return;
  }

  setDebugStatus('Loading chunks...');
  clearDebugChunks('Loading chunks...');

  try {
    const data = await fetchJSON(
      `/api/debug/chunks/${encodeURIComponent(repoId)}?relpath_key=${encodeURIComponent(relpathKey)}`
    );
    if (state.debugRepoId !== repoId || state.debugFileKey !== relpathKey) {
      return;
    }
    renderDebugChunks(data);
    const expected = Number(data.expected_chunks || 0);
    const missing = Number(data.missing_chunks || 0);
    if (missing > 0) {
      setDebugStatus(`Loaded ${expected} (${missing} missing)`);
    } else {
      setDebugStatus(`Loaded ${expected}`);
    }
  } catch (err) {
    setDebugStatus('Error');
    clearDebugChunks(`Error loading chunks: ${err.message}`);
  }
}

async function submitRepoCreate() {
  const nameInput = qs('#repo-create-name');
  const idInput = qs('#repo-create-id');
  const errorEl = qs('#repo-create-error');
  const saveBtn = qs('#repo-create-save');
  const cancelBtn = qs('#repo-create-cancel');
  if (!nameInput || !idInput) return;

  const errorMsg = validateRepoCreate(nameInput.value, idInput.value);
  if (errorEl) errorEl.textContent = errorMsg;
  if (errorMsg) return;

  const payload = {
    display_name: nameInput.value.trim(),
    repo_id: idInput.value.trim(),
  };

  if (saveBtn) saveBtn.disabled = true;
  if (cancelBtn) cancelBtn.disabled = true;

  try {
    await fetchJSON('/api/repos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.createdRepoId = payload.repo_id;
    await loadRepos();
    showRepoCreatePanel(false);
    resetRepoCreateForm();
    const success = qs('#repo-create-success');
    if (success) {
      success.classList.remove('hidden');
    }
  } catch (err) {
    if (errorEl) errorEl.textContent = `Error: ${err.message}`;
  } finally {
    if (saveBtn) saveBtn.disabled = false;
    if (cancelBtn) cancelBtn.disabled = false;
  }
}

function validateDisplayName(name, repoId) {
  const trimmed = (name || '').trim();
  if (!trimmed) return 'Name cannot be empty.';
  if (trimmed.indexOf('::') !== -1) return 'Name cannot contain "::".';
  if (trimmed.length > DISPLAY_NAME_MAX) {
    return `Name must be ${DISPLAY_NAME_MAX} characters or fewer.`;
  }
  const lower = trimmed.toLowerCase();
  const conflict = state.repos.find((repo) => {
    const current = displayNameFor(repo).toLowerCase();
    return repo.repo_id !== repoId && current === lower;
  });
  if (conflict) {
    return `Name already used by ${displayNameFor(conflict)}.`;
  }
  return '';
}

function startRepoRename(repoId) {
  if (!repoId) return;
  if (state.editingRepoId === repoId) return;
  state.editingRepoId = repoId;
  renderRepos();
}

function cancelRepoRename() {
  state.editingRepoId = null;
  renderRepos();
}

async function submitRepoRename(repoId, name, saveBtn, cancelBtn, input, errorEl) {
  const errorMsg = validateDisplayName(name, repoId);
  if (errorMsg) {
    errorEl.textContent = errorMsg;
    return;
  }

  const trimmed = name.trim();
  saveBtn.disabled = true;
  cancelBtn.disabled = true;
  input.disabled = true;
  const priorLabel = saveBtn.textContent;
  saveBtn.textContent = 'Saving...';

  try {
    await fetchJSON(`/api/repos/${encodeURIComponent(repoId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: trimmed }),
    });
    state.editingRepoId = null;
    await loadRepos();
  } catch (err) {
    errorEl.textContent = `Error: ${err.message}`;
    saveBtn.disabled = false;
    cancelBtn.disabled = false;
    input.disabled = false;
    saveBtn.textContent = priorLabel;
  }
}

async function handleDeleteRepo(repo) {
  if (!repo || !repo.repo_id) return;
  if (repo.repo_id === DEFAULT_REPO_ID) {
    window.alert('Default repo cannot be deleted.');
    return;
  }
  const name = displayNameFor(repo) || repo.repo_id;
  const ok = window.confirm(
    `Delete repository "${name}" (ID: ${repo.repo_id})?\nThis removes its vectors and state.`
  );
  if (!ok) return;

  try {
    await fetchJSON(`/api/repos/${encodeURIComponent(repo.repo_id)}`, {
      method: 'DELETE',
    });
    if (state.editingRepoId === repo.repo_id) {
      state.editingRepoId = null;
    }
    await loadRepos();
  } catch (err) {
    window.alert(`Delete failed: ${err.message}`);
  }
}

function updateHealthPill() {
  const pill = qs('#health-pill');
  if (!state.health) {
    pill.textContent = 'Health unknown';
    pill.style.background = 'rgba(217, 121, 43, 0.12)';
    pill.style.color = '#d9792b';
    return;
  }
  if (state.health.ok) {
    pill.textContent = `Qdrant OK • ${state.health.point_count ?? 0} points`;
    pill.style.background = 'rgba(31, 111, 120, 0.15)';
    pill.style.color = '#1f6f78';
  } else {
    pill.textContent = 'Health degraded';
    pill.style.background = 'rgba(217, 121, 43, 0.18)';
    pill.style.color = '#d9792b';
  }
}

async function loadHealth() {
  try {
    state.health = await fetchJSON('/api/health');
    qs('#health-json').textContent = JSON.stringify(state.health, null, 2);
  } catch (err) {
    qs('#health-json').textContent = `Error: ${err.message}`;
  }
  updateHealthPill();
}

function fillPathSuggestions() {
  const dataList = qs('#path-suggestions');
  if (!dataList) return;
  dataList.innerHTML = '';
  const roots = state.allowedIngestRoots.length
    ? state.allowedIngestRoots
    : ['/data/input'];
  roots.forEach((root) => {
    const opt = document.createElement('option');
    opt.value = root;
    dataList.appendChild(opt);
  });
  state.repos.forEach((repo) => {
    const roots = collectRoots(repo);
    roots.forEach((root) => {
      const opt = document.createElement('option');
      opt.value = root;
      dataList.appendChild(opt);
    });
  });
}


function setIngestRepoMode(mode) {
  let nextMode = mode === 'new' ? 'new' : 'existing';
  if (nextMode === 'existing' && !state.repos.length) {
    nextMode = 'new';
  }
  state.ingestRepoMode = nextMode;
  const repoField = qs('#ingest-repo-field');
  const deleteControls = qs('#ingest-delete-controls');
  if (repoField) {
    repoField.classList.toggle('is-new', nextMode === 'new');
  }
  if (deleteControls) {
    deleteControls.classList.toggle('hidden', nextMode === 'new');
  }
  qsa('#ingest-repo-mode .segmented-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.mode === nextMode);
  });
  qsa('#ingest-repo-pickers .repo-picker').forEach((picker) => {
    picker.classList.toggle('hidden', picker.dataset.mode !== nextMode);
  });
  if (nextMode === 'new') {
    syncIngestNewRepoIdFromName();
    updateIngestNewRepoState();
  } else {
    const errorEl = qs('#ingest-repo-new-error');
    if (errorEl) errorEl.textContent = '';
    ensureIngestDefaultSelection();
    renderIngestRepoSelector();
  }
}

function getIngestRepoId() {
  if (state.ingestRepoMode === 'new') {
    const input = qs('#ingest-repo-new-id');
    return input ? input.value.trim() : '';
  }
  return '';
}

function getIngestNewRepoName() {
  const input = qs('#ingest-repo-new-name');
  return input ? input.value.trim() : '';
}

function setIngestRepoSelection(repoId) {
  if (repoId) {
    state.ingestSelectedRepoIds.clear();
    state.ingestSelectedRepoGroups.clear();
    state.ingestSelectedRepoIds.add(repoId);
  }
  state.ingestNewRepoIdTouched = false;
  setIngestRepoMode('existing');
  renderIngestRepoSelector();
}

function renderRepos() {
  const tbody = qs('#repos-table tbody');
  const empty = qs('#repos-empty');
  const success = qs('#repo-create-success');
  tbody.innerHTML = '';
  if (!state.repos.length) {
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  if (success && !state.createdRepoId) {
    success.classList.add('hidden');
  }

  state.repos.forEach((repo) => {
    const row = document.createElement('tr');
    const isEditing = state.editingRepoId === repo.repo_id;
    if (isEditing) {
      row.classList.add('row-editing');
    }

    const repoCell = document.createElement('td');
    const originalName = displayNameFor(repo) || repo.repo_id || '';
    const displayLabel = originalName || '—';
    if (isEditing) {
      const editWrap = document.createElement('div');
      editWrap.className = 'repo-edit';
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'repo-input';
      input.value = originalName;
      input.maxLength = DISPLAY_NAME_MAX;
      editWrap.appendChild(input);
      repoCell.appendChild(editWrap);

      const errorEl = document.createElement('div');
      errorEl.className = 'repo-error';
      repoCell.appendChild(errorEl);

      const idEl = document.createElement('div');
      idEl.className = 'repo-id';
      idEl.textContent = repo.repo_id ? `ID: ${repo.repo_id}` : 'ID: —';
      repoCell.appendChild(idEl);

      const actionCell = document.createElement('td');
      const saveBtn = document.createElement('button');
      saveBtn.textContent = 'Save';
      saveBtn.className = 'primary action';
      saveBtn.disabled = true;
      const cancelBtn = document.createElement('button');
      cancelBtn.textContent = 'Cancel';
      cancelBtn.className = 'ghost action';

      const updateState = () => {
        const errorMsg = validateDisplayName(input.value, repo.repo_id);
        errorEl.textContent = errorMsg;
        const changed = input.value.trim() !== originalName;
        saveBtn.disabled = Boolean(errorMsg) || !changed;
      };

      input.addEventListener('input', updateState);
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          cancelRepoRename();
          return;
        }
        if (event.key === 'Enter') {
          event.preventDefault();
          if (!saveBtn.disabled) {
            submitRepoRename(
              repo.repo_id,
              input.value,
              saveBtn,
              cancelBtn,
              input,
              errorEl
            );
          }
        }
      });

      saveBtn.addEventListener('click', () => {
        submitRepoRename(
          repo.repo_id,
          input.value,
          saveBtn,
          cancelBtn,
          input,
          errorEl
        );
      });
      cancelBtn.addEventListener('click', cancelRepoRename);

      updateState();
      setTimeout(() => {
        input.focus();
        input.select();
      }, 0);

      actionCell.appendChild(saveBtn);
      actionCell.appendChild(cancelBtn);

      const rootCell = document.createElement('td');
      renderRootCell(rootCell, repo);

      const filesCell = document.createElement('td');
      filesCell.textContent = repo.file_count ?? 0;

      const lastRunCell = document.createElement('td');
      lastRunCell.textContent = formatTime(repo.last_run_ts);

      row.appendChild(repoCell);
      row.appendChild(rootCell);
      row.appendChild(filesCell);
      row.appendChild(lastRunCell);
      row.appendChild(actionCell);

      tbody.appendChild(row);
      return;
    }

    const nameEl = document.createElement('div');
    nameEl.className = 'repo-name';
    nameEl.textContent = displayLabel;
    nameEl.title = 'Double-click to rename';
    nameEl.addEventListener('dblclick', () => {
      startRepoRename(repo.repo_id);
    });
    repoCell.appendChild(nameEl);

    const idEl = document.createElement('div');
    idEl.className = 'repo-id';
    idEl.textContent = repo.repo_id ? `ID: ${repo.repo_id}` : 'ID: —';
    repoCell.appendChild(idEl);

    const rootCell = document.createElement('td');
    renderRootCell(rootCell, repo);

    const filesCell = document.createElement('td');
    filesCell.textContent = repo.file_count ?? 0;

    const lastRunCell = document.createElement('td');
    lastRunCell.textContent = formatTime(repo.last_run_ts);

    const actionCell = document.createElement('td');
    const askBtn = document.createElement('button');
    askBtn.textContent = 'Ask scoped';
    askBtn.className = 'ghost action';
    askBtn.addEventListener('click', () => {
      state.allRepos = false;
      state.selectedRepoIds.clear();
      state.selectedRepoGroups.clear();
      if (repo.repo_id) {
        state.selectedRepoIds.add(repo.repo_id);
      }
      renderRepoSelector();
      setActiveTab('ask');
    });

    const ingestBtn = document.createElement('button');
    ingestBtn.textContent = 'Ingest now';
    ingestBtn.className = 'ghost action';
    ingestBtn.addEventListener('click', () => {
      const roots = collectRoots(repo);
      qs('#ingest-path').value = roots.length ? roots[0] : '';
      if (repo.repo_id) {
        setIngestRepoSelection(repo.repo_id);
      }
      setActiveTab('ingest');
    });

    const renameBtn = document.createElement('button');
    renameBtn.textContent = 'Rename';
    renameBtn.className = 'ghost action';
    renameBtn.addEventListener('click', () => {
      startRepoRename(repo.repo_id);
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.textContent = 'Delete';
    deleteBtn.className = 'ghost action danger';
    if (repo.repo_id === DEFAULT_REPO_ID) {
      deleteBtn.disabled = true;
      deleteBtn.title = 'Default repo cannot be deleted';
    }
    deleteBtn.addEventListener('click', () => {
      handleDeleteRepo(repo);
    });

    actionCell.appendChild(askBtn);
    actionCell.appendChild(ingestBtn);
    actionCell.appendChild(renameBtn);
    actionCell.appendChild(deleteBtn);

    row.appendChild(repoCell);
    row.appendChild(rootCell);
    row.appendChild(filesCell);
    row.appendChild(lastRunCell);
    row.appendChild(actionCell);

    tbody.appendChild(row);
  });
}

async function loadRepos() {
  try {
    const data = await fetchJSON('/api/repos');
    state.repos = data.repos || [];
    if (
      state.editingRepoId &&
      !state.repos.some((repo) => repo.repo_id === state.editingRepoId)
    ) {
      state.editingRepoId = null;
    }
    if (
      state.createdRepoId &&
      !state.repos.some((repo) => repo.repo_id === state.createdRepoId)
    ) {
      state.createdRepoId = null;
    }
    const knownIds = new Set(
      state.repos.map((repo) => repo.repo_id).filter((repoId) => repoId)
    );
    state.selectedRepoIds.forEach((repoId) => {
      if (!knownIds.has(repoId)) {
        state.selectedRepoIds.delete(repoId);
      }
    });
    state.ingestSelectedRepoIds.forEach((repoId) => {
      if (!knownIds.has(repoId)) {
        state.ingestSelectedRepoIds.delete(repoId);
      }
    });
    if (!state.selectedRepoIds.size && !state.selectedRepoGroups.size) {
      state.allRepos = true;
    }
    ensureIngestDefaultSelection(knownIds);
    if (
      state.debugRepoId &&
      !knownIds.has(state.debugRepoId)
    ) {
      state.debugRepoId = '';
      state.debugFileKey = '';
      state.debugFilesRepoId = '';
      state.debugFiles = [];
    }
    renderRepos();
    renderRepoSelector();
    if (window.renderRepoGroupsManager) {
      window.renderRepoGroupsManager();
    }
    renderIngestRepoSelector();
    renderDebugRepoSelector();
    fillPathSuggestions();
  } catch (err) {
    qs('#repos-empty').textContent = `Error: ${err.message}`;
  }
}

async function loadRepoGroups() {
  try {
    const data = await fetchJSON('/api/repo-groups');
    state.repoGroups = data.groups || [];
    const knownGroups = new Set(
      state.repoGroups.map((group) => group.name).filter((name) => name)
    );
    state.selectedRepoGroups.forEach((groupName) => {
      if (!knownGroups.has(groupName)) {
        state.selectedRepoGroups.delete(groupName);
      }
    });
    state.ingestSelectedRepoGroups.forEach((groupName) => {
      if (!knownGroups.has(groupName)) {
        state.ingestSelectedRepoGroups.delete(groupName);
      }
    });
    if (!state.selectedRepoIds.size && !state.selectedRepoGroups.size) {
      state.allRepos = true;
    }
    ensureIngestDefaultSelection();
    renderRepoSelector();
    if (window.renderRepoGroupsManager) {
      window.renderRepoGroupsManager();
    }
    renderIngestRepoSelector();
  } catch (err) {
    state.repoGroups = [];
    const empty = qs('#repo-groups-empty');
    if (empty) {
      empty.textContent = `Error: ${err.message}`;
    }
    renderRepoSelector();
  }
}

function renderAnswer(data) {
  const answer = data.answer || '';
  qs('#answer-output').innerHTML = renderMarkdown(answer);
  const citationsList = qs('#citations-list');
  citationsList.innerHTML = '';
  (data.citations || []).forEach((c) => {
    const li = document.createElement('li');
    const label = `[path=${c.path} chunk=${c.chunk}]`;
    const fileUrl = wslToFileUrl(c.path);
    if (fileUrl) {
      const link = document.createElement('a');
      link.href = fileUrl;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = label;
      li.appendChild(link);
    } else {
      li.textContent = label;
    }
    citationsList.appendChild(li);
  });

  const sourcesList = qs('#sources-list');
  sourcesList.innerHTML = '';
  (data.sources || []).forEach((s) => {
    const div = document.createElement('div');
    div.className = 'source-item';
    const preview = s.text_preview ? s.text_preview : 'Preview unavailable (answer.py did not emit text).';
    div.innerHTML = `<strong>${s.path}</strong><div>chunk ${s.chunk} • score ${s.score ?? 'n/a'}</div><div class=\"preview\">${preview}</div>`;
    sourcesList.appendChild(div);
  });
}

function wslToFileUrl(path) {
  if (!path) return null;
  const prefix = '/mnt/';
  if (!path.startsWith(prefix)) return null;
  const drive = path.slice(prefix.length, prefix.length + 1);
  const slash = path.slice(prefix.length + 1, prefix.length + 2);
  if (!drive || !drive.match(/^[a-zA-Z]$/) || slash !== '/') return null;
  const rest = path.slice(prefix.length + 2);
  const url = `file:///${drive.toUpperCase()}:/${rest}`;
  return encodeURI(url);
}

async function handleAskSubmit(event) {
  event.preventDefault();
  if (!isOpenAIConfigured()) {
    setActiveTab('settings');
    qs('#answer-output').textContent =
      'OpenAI API key is not configured. Set it in Settings first.';
    return;
  }
  const question = qs('#ask-question').value.trim();
  if (!question) {
    qs('#answer-output').textContent = 'Please enter a question.';
    return;
  }

  const repoIds = Array.from(state.selectedRepoIds);
  const repoGroups = Array.from(state.selectedRepoGroups);
  const allRepos = state.allRepos || (!repoIds.length && !repoGroups.length);
  const payload = {
    question,
    all_repos: allRepos,
    repo_ids: allRepos ? null : repoIds,
    repo_groups: allRepos ? null : repoGroups,
    top_k: Number(qs('#ask-topk').value || 10),
    show_sources: qs('#ask-sources').checked,
  };

  qs('#answer-output').textContent = 'Thinking...';
  qs('#citations-list').innerHTML = '';
  qs('#sources-list').innerHTML = '';

  try {
    const data = await fetchJSON('/api/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderAnswer(data);
  } catch (err) {
    qs('#answer-output').textContent = `Error: ${err.message}`;
  }
}

function appendLog(line) {
  const log = qs('#ingest-logs');
  log.textContent += `${line}\n`;
  log.scrollTop = log.scrollHeight;
}

function setIngestStatus(text) {
  qs('#ingest-status').textContent = text;
}

function stopEventSource() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

async function handleIngestSubmit(event) {
  event.preventDefault();
  if (!isOpenAIConfigured()) {
    setActiveTab('settings');
    setIngestStatus('Blocked');
    qs('#ingest-logs').textContent = '';
    appendLog('ERROR: OpenAI API key is not configured. Set it in Settings first.');
    return;
  }
  stopEventSource();
  qs('#ingest-logs').textContent = '';
  setIngestStatus('Starting...');

  const pathValue = qs('#ingest-path').value.trim();
  let repoIds = [];
  let repoGroups = [];

  if (state.ingestRepoMode === 'new') {
    const repoId = getIngestRepoId();
    const repoName = getIngestNewRepoName();
    const errorEl = qs('#ingest-repo-new-error');
    const errorMsg = validateRepoCreate(repoName, repoId);
    if (errorEl) {
      errorEl.textContent = errorMsg;
    }
    if (errorMsg) {
      setIngestStatus('Error');
      appendLog(`ERROR: ${errorMsg}`);
      return;
    }
    try {
      await fetchJSON('/api/repos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: repoName, repo_id: repoId }),
      });
      await loadRepos();
      setIngestRepoSelection(repoId);
    } catch (err) {
      const msg = `Create repo failed: ${err.message}`;
      if (errorEl) {
        errorEl.textContent = msg;
      }
      setIngestStatus('Error');
      appendLog(`ERROR: ${msg}`);
      return;
    }
    repoIds = [repoId];
  } else {
    repoIds = Array.from(state.ingestSelectedRepoIds);
    repoGroups = Array.from(state.ingestSelectedRepoGroups);
    if (!repoIds.length && !repoGroups.length) {
      if (state.repos.some((repo) => repo.repo_id === DEFAULT_REPO_ID)) {
        repoIds = [DEFAULT_REPO_ID];
        state.ingestSelectedRepoIds.clear();
        state.ingestSelectedRepoGroups.clear();
        state.ingestSelectedRepoIds.add(DEFAULT_REPO_ID);
        renderIngestRepoSelector();
      } else {
        setIngestStatus('Error');
        appendLog('ERROR: select at least one repo or group.');
        return;
      }
    }
  }

  const payload = {
    path: pathValue,
    repo_ids: repoIds.length ? repoIds : null,
    repo_groups: repoGroups.length ? repoGroups : null,
    all_repos: false,
    delete_missing:
      state.ingestRepoMode === 'existing' && Boolean(qs('#ingest-delete')?.checked),
  };

  try {
    const data = await fetchJSON('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (data.warnings && Array.isArray(data.warnings)) {
      data.warnings.forEach((line) => appendLog(`WARN: ${line}`));
    }
    setIngestStatus(`Running (${data.job_id})`);
    const evt = new EventSource(`/api/ingest/${data.job_id}/events`);
    state.eventSource = evt;

    evt.addEventListener('log', (msg) => {
      const data = JSON.parse(msg.data);
      appendLog(data.line);
    });

    evt.addEventListener('error', (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.status) {
          appendLog(`DONE status=${data.status} returncode=${data.returncode}`);
          if (data.stderr && Array.isArray(data.stderr)) {
            data.stderr.forEach((line) => appendLog(`ERR: ${line}`));
          }
        } else {
          appendLog(`ERROR: ${data.error || 'unknown error'}`);
        }
      } catch (err) {
        appendLog('ERROR: ingest failed');
      }
      setIngestStatus('Error');
      evt.close();
      loadRepos();
    });

    evt.addEventListener('done', (msg) => {
      const info = JSON.parse(msg.data);
      appendLog(`DONE status=${info.status} returncode=${info.returncode}`);
      setIngestStatus(info.status === 'done' ? 'Done' : 'Error');
      evt.close();
      loadRepos();
    });
  } catch (err) {
    setIngestStatus('Error');
    appendLog(`ERROR: ${err.message}`);
  }
}

function bindTabs() {
  qsa('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      setActiveTab(btn.dataset.tab);
    });
  });
}

function bindActions() {
  qs('#ask-form').addEventListener('submit', handleAskSubmit);
  qs('#ingest-form').addEventListener('submit', handleIngestSubmit);
  qs('#repos-refresh').addEventListener('click', loadRepos);
  qs('#health-refresh').addEventListener('click', loadHealth);
  const settingsSave = qs('#settings-openai-save');
  if (settingsSave) {
    settingsSave.addEventListener('click', () => {
      const input = qs('#settings-openai-key');
      saveOpenAIKey(input ? input.value : '');
    });
  }
  const settingsTest = qs('#settings-openai-test');
  if (settingsTest) {
    settingsTest.addEventListener('click', () => {
      testOpenAIConnection({ useInput: true, silent: false });
    });
  }
  const settingsClear = qs('#settings-openai-clear');
  if (settingsClear) {
    settingsClear.addEventListener('click', clearOpenAIKey);
  }
  const settingsRefresh = qs('#settings-openai-refresh');
  if (settingsRefresh) {
    settingsRefresh.addEventListener('click', () => {
      setSettingsMessage('Refreshing settings...', false);
      loadSettings();
    });
  }
  const gateSave = qs('#settings-gate-save');
  if (gateSave) {
    gateSave.addEventListener('click', () => {
      const input = qs('#settings-gate-key');
      saveOpenAIKey(input ? input.value : '');
    });
  }
  const gateOpen = qs('#settings-gate-open');
  if (gateOpen) {
    gateOpen.addEventListener('click', () => {
      setActiveTab('settings');
      const input = qs('#settings-openai-key');
      if (input) {
        setTimeout(() => {
          input.focus();
        }, 0);
      }
    });
  }
  const askQuestion = qs('#ask-question');
  if (askQuestion) {
    askQuestion.addEventListener('input', updateAskButtonState);
  }
  const repoCreateOpen = qs('#repo-create-open');
  if (repoCreateOpen) {
    repoCreateOpen.addEventListener('click', () => {
      resetRepoCreateForm();
      showRepoCreatePanel(true);
      syncRepoCreateIdFromName();
      updateRepoCreateState();
    });
  }
  const repoCreateCancel = qs('#repo-create-cancel');
  if (repoCreateCancel) {
    repoCreateCancel.addEventListener('click', () => {
      showRepoCreatePanel(false);
      resetRepoCreateForm();
    });
  }
  const repoCreateSave = qs('#repo-create-save');
  if (repoCreateSave) {
    repoCreateSave.addEventListener('click', submitRepoCreate);
  }
  const repoCreateName = qs('#repo-create-name');
  const repoCreateId = qs('#repo-create-id');
  if (repoCreateName) {
    repoCreateName.addEventListener('input', () => {
      syncRepoCreateIdFromName();
      updateRepoCreateState();
    });
  }
  if (repoCreateId) {
    repoCreateId.addEventListener('input', () => {
      state.repoCreateIdTouched = Boolean(repoCreateId.value.trim());
      updateRepoCreateState();
    });
  }
  const ingestNewName = qs('#ingest-repo-new-name');
  const ingestNewId = qs('#ingest-repo-new-id');
  if (ingestNewName) {
    ingestNewName.addEventListener('input', () => {
      syncIngestNewRepoIdFromName();
      updateIngestNewRepoState();
    });
  }
  if (ingestNewId) {
    ingestNewId.addEventListener('input', () => {
      state.ingestNewRepoIdTouched = Boolean(ingestNewId.value.trim());
      updateIngestNewRepoState();
    });
  }
  const repoCreateIngest = qs('#repo-create-ingest');
  if (repoCreateIngest) {
    repoCreateIngest.addEventListener('click', () => {
      if (state.createdRepoId) {
        setIngestRepoSelection(state.createdRepoId);
        setActiveTab('ingest');
      }
    });
  }
  const ingestPath = qs('#ingest-path');
  if (ingestPath) {
    ingestPath.addEventListener('input', updateIngestButtonState);
  }
  qsa('#ingest-repo-mode .segmented-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      setIngestRepoMode(btn.dataset.mode);
    });
  });
  const ingestFilter = qs('#ingest-repo-filter');
  if (ingestFilter) {
    ingestFilter.addEventListener('input', (event) => {
      state.ingestRepoFilter = event.target.value;
      renderIngestRepoSelector();
    });
  }
  const ingestNewNameFocus = qs('#ingest-repo-new-name');
  if (ingestNewNameFocus) {
    ingestNewNameFocus.addEventListener('focus', () => {
      setIngestRepoMode('new');
    });
  }
  const ingestNewIdFocus = qs('#ingest-repo-new-id');
  if (ingestNewIdFocus) {
    ingestNewIdFocus.addEventListener('focus', () => {
      setIngestRepoMode('new');
    });
  }
  const debugRepo = qs('#debug-repo');
  if (debugRepo) {
    debugRepo.addEventListener('change', (event) => {
      state.debugRepoId = event.target.value || '';
      state.debugFileKey = '';
      state.debugFiles = [];
      state.debugFilesRepoId = '';
      renderDebugFileSelector();
      if (!state.debugRepoId) {
        setDebugStatus('Idle');
        clearDebugChunks('Select a file and load chunks.');
        return;
      }
      loadDebugFiles(state.debugRepoId);
    });
  }
  const debugFile = qs('#debug-file');
  if (debugFile) {
    debugFile.addEventListener('change', (event) => {
      state.debugFileKey = event.target.value || '';
      updateDebugFileMeta();
      updateDebugLoadButtonState();
    });
  }
  const debugLoad = qs('#debug-load');
  if (debugLoad) {
    debugLoad.addEventListener('click', loadDebugChunks);
  }
  const allReposToggle = qs('#ask-all-repos');
  if (allReposToggle) {
    allReposToggle.addEventListener('change', (event) => {
      setAllRepos(event.target.checked);
    });
  }
  const filterInput = qs('#repo-filter');
  if (filterInput) {
    filterInput.addEventListener('input', (event) => {
      state.repoFilter = event.target.value;
      renderRepoSelector();
    });
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  bindTabs();
  bindActions();
  updateAskButtonState();
  setIngestRepoMode(state.ingestRepoMode);
  updateIngestButtonState();
  setDebugStatus('Idle');
  clearDebugChunks('Select a file and load chunks.');
  updateDebugLoadButtonState();
  setSettingsMessage('', false);
  setSettingsGateMessage('', false);
  await loadSettings();
  loadHealth();
  loadRepos();
  loadRepoGroups();
  fillPathSuggestions();
});
