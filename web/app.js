const state = {
  defaultSource: 'data/captures/raw',
  defaultOut: '.media-ark',
};

function el(selector) {
  return document.querySelector(selector);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'content-type': 'application/json' },
    ...options,
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

function onError(error) {
  el('#lastRun').textContent = `${new Date().toISOString()}\n${String(error.message || error)}`;
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
  bindActions();
  await refreshStatus();
  await refreshIndex().catch(() => {});
  setInterval(() => refreshStatus().catch(() => {}), 8000);
}

window.addEventListener('load', () => {
  bootstrap().catch(onError);
});
