const state = {
  apiKey: localStorage.getItem('mediaArkApiKey') || '',
  defaultSource: localStorage.getItem('mediaArkSource') || 'data/captures/raw',
  defaultOut: localStorage.getItem('mediaArkOut') || '.media-ark',
};

function el(selector) {
  return document.querySelector(selector);
}

async function requestJson(url, options = {}) {
  const headers = {
    'content-type': 'application/json',
    ...(options.headers || {}),
  };
  if (state.apiKey && !headers.Authorization) {
    headers.Authorization = `Bearer ${state.apiKey}`;
  }
  const response = await fetch(url, {
    ...options,
    headers,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || payload.message || `Request failed: ${response.status}`);
  }
  return payload;
}

function currentPayload() {
  return {
    source: el('#sourcePath').value.trim() || state.defaultSource,
    out: el('#outPath').value.trim() || state.defaultOut,
    copy: el('#copyMode').checked,
    max_files: Number(el('#maxFiles').value || 0),
    dry_run: el('#dryRun').checked,
  };
}

function renderStatus(payload) {
  el('#sourceStatus').textContent = payload.source || '-';
  el('#outStatus').textContent = payload.out || '-';
  el('#manifestStatus').textContent = payload.manifest_exists ? 'present' : 'missing';
  el('#indexRows').textContent = String(payload.index_rows || 0);
}

function renderResults(payload) {
  const block = el('#results');
  block.textContent = JSON.stringify(payload, null, 2);
}

function renderLastRun(payload) {
  el('#lastRun').textContent = JSON.stringify(payload, null, 2);
}

function renderAuthStatus(text) {
  const target = el('#authStatus');
  if (target) {
    target.textContent = text;
  }
}

function onError(error) {
  el('#lastRun').textContent = `${new Date().toISOString()}\n${String(error.message || error)}`;
}

function applyAuth(payload) {
  state.apiKey = payload.api_key || state.apiKey;
  state.defaultSource = payload.source || state.defaultSource;
  state.defaultOut = payload.out || state.defaultOut;
  localStorage.setItem('mediaArkApiKey', state.apiKey);
  localStorage.setItem('mediaArkSource', state.defaultSource);
  localStorage.setItem('mediaArkOut', state.defaultOut);
  el('#sourcePath').value = state.defaultSource;
  el('#outPath').value = state.defaultOut;
  renderAuthStatus(`Signed in as ${payload.user?.username || 'user'}`);
}

function authPayload() {
  return {
    username: el('#authUsername').value.trim(),
    password: el('#authPassword').value,
  };
}

async function registerAccount() {
  const payload = await requestJson('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(authPayload()),
  });
  applyAuth(payload);
  await refreshStatus();
}

async function loginAccount() {
  const payload = await requestJson('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(authPayload()),
  });
  applyAuth(payload);
  await refreshStatus();
}

async function rotateApiKey() {
  const payload = await requestJson('/api/auth/api-key', { method: 'POST' });
  applyAuth(payload);
  renderLastRun({ ok: true, api_key_rotated: true, user: payload.user });
}

function signOut() {
  state.apiKey = '';
  localStorage.removeItem('mediaArkApiKey');
  renderAuthStatus('Signed out');
}

async function refreshStatus() {
  const payload = currentPayload();
  const params = new URLSearchParams({ source: payload.source, out: payload.out });
  const status = await requestJson(`/api/status?${params.toString()}`);
  renderStatus(status);
  return status;
}

async function runAction(action) {
  const payload = {
    ...currentPayload(),
    action,
  };
  const response = await requestJson('/api/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  renderLastRun(response);
  await refreshStatus();
}

async function refreshIndex() {
  const { source, out } = currentPayload();
  const query = el('#queryText').value.trim();
  const limit = Number(el('#queryLimit').value || 25);
  const media = (el('#queryMedia')?.value || 'all').trim();
  const status = (el('#queryStatus')?.value || 'all').trim();
  const params = new URLSearchParams({ source, out, limit: String(limit), media, status });
  if (query) {
    params.set('query', query);
  }
  const records = await requestJson(`/api/index?${params.toString()}`);
  renderResults(records);
}

async function runQuery() {
  const payload = {
    ...currentPayload(),
    action: 'query',
    query: el('#queryText').value.trim(),
    query_media: (el('#queryMedia')?.value || 'all').trim(),
    query_status: (el('#queryStatus')?.value || 'all').trim(),
    query_limit: Number(el('#queryLimit').value || 25),
  };
  const response = await requestJson('/api/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  renderLastRun(response);
  if (response.payload) {
    renderResults(response.payload);
  }
}

function bindActions() {
  document.body.addEventListener('click', (event) => {
    const action = event.target?.dataset?.action;
    if (!action) {
      return;
    }
    event.preventDefault();
    if (action === 'register') {
      registerAccount().catch(onError);
      return;
    }
    if (action === 'login') {
      loginAccount().catch(onError);
      return;
    }
    if (action === 'rotate-api-key') {
      rotateApiKey().catch(onError);
      return;
    }
    if (action === 'sign-out') {
      signOut();
      return;
    }
    if (action === 'check') {
      runAction('check-source').catch(onError);
      return;
    }
    if (action === 'process') {
      runAction('process').catch(onError);
      return;
    }
    if (action === 'verify') {
      runAction('verify').catch(onError);
      return;
    }
    if (action === 'query') {
      runQuery().catch(onError);
      return;
    }
    if (action === 'refresh-index') {
      refreshIndex().catch(onError);
      return;
    }
  });
}

async function bootstrap() {
  el('#sourcePath').value = state.defaultSource;
  el('#outPath').value = state.defaultOut;
  bindActions();
  if (state.apiKey) {
    renderAuthStatus('Signed in');
    await refreshStatus();
    await refreshIndex().catch(() => {});
  } else {
    renderAuthStatus('Signed out');
  }
  setInterval(() => refreshStatus().catch(() => {}), 8000);
}

window.addEventListener('load', () => {
  bootstrap().catch(onError);
});
