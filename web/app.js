const state = {
  defaultSource: 'data/captures/raw',
  defaultOut: '.media-ark',
  user: null,
  quotaUsed: 0,
};

const AUTH_STORAGE_KEY = 'mediaArk.dashboard.auth';
const QUOTA_WARN_PERCENT = 80;

const PRO_FEATURE_FLAGS = {
  advancedFilters: 'Advanced filters',
  bulkProcessing: 'Bulk processing',
  verificationReports: 'Verification reports',
  expandedQuota: 'Expanded quota',
};

const PLAN_CONFIG = {
  free: {
    label: 'Starter',
    quota: 100,
    maxFilesPerRun: 25,
    flags: {
      advancedFilters: false,
      bulkProcessing: false,
      verificationReports: false,
      expandedQuota: false,
    },
  },
  pro: {
    label: 'Pro',
    quota: 1000,
    maxFilesPerRun: 50000,
    flags: {
      advancedFilters: true,
      bulkProcessing: true,
      verificationReports: true,
      expandedQuota: true,
    },
  },
};

function el(selector) {
  return document.querySelector(selector);
}

function activePlan() {
  if (!state.user) {
    return PLAN_CONFIG.free;
  }
  return PLAN_CONFIG[state.user.plan] || PLAN_CONFIG.free;
}

function activeFlags() {
  return activePlan().flags;
}

function isAuthenticated() {
  return Boolean(state.user?.email);
}

function safeStorageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function safeStorageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (error) {
    // Local storage can be unavailable in hardened browser modes.
  }
}

function safeStorageRemove(key) {
  try {
    window.localStorage.removeItem(key);
  } catch (error) {
    // Local storage can be unavailable in hardened browser modes.
  }
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

function injectDashboardStyles() {
  if (el('#dashboardAuthStyles')) {
    return;
  }
  const style = document.createElement('style');
  style.id = 'dashboardAuthStyles';
  style.textContent = `
    .auth-card,
    .pro-feature-card {
      margin-bottom: 12px;
    }

    .auth-layout {
      display: grid;
      grid-template-columns: minmax(240px, 1fr) minmax(240px, 1fr);
      gap: 12px;
      align-items: start;
    }

    .auth-status,
    .quota-status,
    .feature-note {
      color: #cbd5e1;
      margin: 6px 0 10px;
    }

    .auth-status.error,
    .quota-status.warn {
      color: #fbbf24;
    }

    .quota-meter {
      width: 100%;
      height: 14px;
      accent-color: #22c55e;
    }

    .quota-meter.warn {
      accent-color: #f59e0b;
    }

    .quota-stats {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: #e2e8f0;
      font-size: 0.95rem;
      margin-top: 8px;
    }

    .feature-flags {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 8px;
    }

    .feature-flag {
      border: 1px solid #475569;
      border-radius: 8px;
      padding: 8px 10px;
      background: #0f172a;
    }

    .feature-flag strong {
      display: block;
      color: #f8fafc;
      margin-bottom: 4px;
    }

    .feature-flag span {
      color: #94a3b8;
      font-size: 0.9rem;
    }

    .feature-flag.enabled {
      border-color: #22c55e;
    }

    .feature-flag.enabled span {
      color: #86efac;
    }

    .feature-flag.locked span {
      color: #cbd5e1;
    }

    .dashboard-locked section:not(#authPanel):not(#proFeaturePanel) {
      opacity: 0.55;
    }

    button:disabled,
    input:disabled,
    select:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

    @media (max-width: 700px) {
      .auth-layout,
      .quota-stats {
        grid-template-columns: 1fr;
      }

      .quota-stats {
        display: grid;
      }
    }
  `;
  document.head.appendChild(style);
}

function injectAuthUi() {
  if (el('#authPanel')) {
    return;
  }
  injectDashboardStyles();
  const header = el('header');
  header.insertAdjacentHTML(
    'afterend',
    `
    <section id="authPanel" class="card auth-card">
      <div class="auth-layout">
        <form id="userAuthForm">
          <h2>User Auth</h2>
          <p id="authStatus" class="auth-status">Signed out</p>
          <div class="row">
            <label for="authEmail">Email</label>
            <input id="authEmail" type="email" autocomplete="email" data-auth-control />
          </div>
          <div class="row">
            <label for="authToken">Access key</label>
            <input id="authToken" type="password" autocomplete="current-password" data-auth-control />
          </div>
          <div class="row">
            <label for="authPlan">Plan</label>
            <select id="authPlan" data-auth-control>
              <option value="free">Starter</option>
              <option value="pro">Pro</option>
            </select>
          </div>
          <div class="btn-row">
            <button type="submit" data-auth-control>Sign in</button>
            <button type="button" data-action="auth-signout" data-auth-control>Sign out</button>
          </div>
        </form>
        <div id="quotaPanel">
          <h2>Quota</h2>
          <p id="quotaStatus" class="quota-status">Sign in to load quota.</p>
          <progress id="quotaMeter" class="quota-meter" max="100" value="0"></progress>
          <div class="quota-stats">
            <span id="quotaUsage">0 / 100 records</span>
            <span id="quotaPercent">0%</span>
          </div>
        </div>
      </div>
    </section>
    <section id="proFeaturePanel" class="card pro-feature-card">
      <h2>Pro Feature Flags</h2>
      <p id="featureNote" class="feature-note">Sign in to evaluate feature flags.</p>
      <div id="featureFlags" class="feature-flags"></div>
    </section>
    `,
  );
}

function renderStatus(payload) {
  state.quotaUsed = Number(payload.index_rows || 0);
  el('#sourceStatus').textContent = payload.source || '-';
  el('#outStatus').textContent = payload.out || '-';
  el('#manifestStatus').textContent = payload.manifest_exists ? 'present' : 'missing';
  el('#indexRows').textContent = String(payload.index_rows || 0);
  renderQuota();
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

function renderAuth(message = '') {
  const status = el('#authStatus');
  const signOutButton = el('[data-action="auth-signout"]');
  if (!status || !signOutButton) {
    return;
  }
  status.classList.remove('error');
  if (isAuthenticated()) {
    const plan = activePlan();
    status.textContent = message || `Signed in as ${state.user.email} (${plan.label})`;
    el('#authEmail').value = state.user.email;
    el('#authPlan').value = state.user.plan;
    signOutButton.disabled = false;
  } else {
    status.textContent = message || 'Signed out';
    signOutButton.disabled = true;
  }
}

function renderAuthError(message) {
  const status = el('#authStatus');
  if (!status) {
    return;
  }
  status.textContent = message;
  status.classList.add('error');
}

function renderFeatureFlags() {
  const container = el('#featureFlags');
  const note = el('#featureNote');
  if (!container || !note) {
    return;
  }
  const flags = activeFlags();
  const plan = activePlan();
  container.innerHTML = '';
  note.textContent = isAuthenticated()
    ? `${plan.label} plan active`
    : 'Sign in to evaluate feature flags.';

  Object.entries(PRO_FEATURE_FLAGS).forEach(([key, label]) => {
    const enabled = Boolean(flags[key]);
    const item = document.createElement('div');
    item.className = `feature-flag ${enabled ? 'enabled' : 'locked'}`;

    const title = document.createElement('strong');
    title.textContent = label;
    item.appendChild(title);

    const stateText = document.createElement('span');
    stateText.textContent = enabled ? 'Enabled' : 'Locked';
    item.appendChild(stateText);

    container.appendChild(item);
  });
}

function renderQuota() {
  const quotaMeter = el('#quotaMeter');
  const quotaStatus = el('#quotaStatus');
  const quotaUsage = el('#quotaUsage');
  const quotaPercent = el('#quotaPercent');
  if (!quotaMeter || !quotaStatus || !quotaUsage || !quotaPercent) {
    return;
  }
  const plan = activePlan();
  const used = Math.max(0, Number(state.quotaUsed || 0));
  const usageRatio = plan.quota > 0 ? used / plan.quota : 0;
  const percent = Math.min(100, Math.round(usageRatio * 100));
  const warn = isAuthenticated() && usageRatio >= QUOTA_WARN_PERCENT / 100;

  quotaMeter.value = percent;
  quotaMeter.classList.toggle('warn', warn);
  quotaStatus.classList.toggle('warn', warn);
  quotaUsage.textContent = `${used} / ${plan.quota} records`;
  quotaPercent.textContent = `${percent}%`;

  if (!isAuthenticated()) {
    quotaStatus.textContent = 'Sign in to load quota.';
  } else if (warn) {
    quotaStatus.textContent = `Warning: ${percent}% of quota used.`;
  } else {
    quotaStatus.textContent = `${plan.label} quota active.`;
  }
}

function renderAuthDependentUi() {
  const signedIn = isAuthenticated();
  const quotaPanel = el('#quotaPanel');
  const proFeaturePanel = el('#proFeaturePanel');

  document.body.classList.toggle('dashboard-locked', !signedIn);
  if (quotaPanel) {
    quotaPanel.hidden = !signedIn;
  }
  if (proFeaturePanel) {
    proFeaturePanel.hidden = !signedIn;
  }
  renderAuth();
  renderFeatureFlags();
  renderQuota();
  applyAccessControls();
}

function restoreAuthSession() {
  const raw = safeStorageGet(AUTH_STORAGE_KEY);
  if (!raw) {
    return;
  }
  try {
    const session = JSON.parse(raw);
    const plan = PLAN_CONFIG[session.plan] ? session.plan : 'free';
    if (typeof session.email === 'string' && session.email.includes('@')) {
      state.user = {
        email: session.email,
        plan,
        signedInAt: session.signedInAt || new Date().toISOString(),
      };
    }
  } catch (error) {
    safeStorageRemove(AUTH_STORAGE_KEY);
  }
}

function persistAuthSession() {
  if (!state.user) {
    safeStorageRemove(AUTH_STORAGE_KEY);
    return;
  }
  safeStorageSet(AUTH_STORAGE_KEY, JSON.stringify(state.user));
}

function signOut() {
  state.user = null;
  state.quotaUsed = 0;
  persistAuthSession();
  renderAuthDependentUi();
}

async function signIn() {
  const email = el('#authEmail').value.trim();
  const token = el('#authToken').value.trim();
  const plan = PLAN_CONFIG[el('#authPlan').value] ? el('#authPlan').value : 'free';

  if (!email || !email.includes('@')) {
    renderAuthError('Enter a valid email.');
    return;
  }
  if (token.length < 4) {
    renderAuthError('Enter an access key.');
    return;
  }

  state.user = {
    email,
    plan,
    signedInAt: new Date().toISOString(),
  };
  el('#authToken').value = '';
  persistAuthSession();
  renderAuthDependentUi();
  await loadDashboard();
}

function requireUserAuth() {
  if (isAuthenticated()) {
    return true;
  }
  renderAuthError('Sign in to continue.');
  renderLastRun({
    ok: false,
    error: 'auth_required',
    message: 'Sign in before using dashboard actions.',
  });
  applyAccessControls();
  return false;
}

function quotaRemaining() {
  return Math.max(0, activePlan().quota - Number(state.quotaUsed || 0));
}

function payloadForAction(action) {
  const payload = {
    ...currentPayload(),
    action,
  };
  if (action !== 'process') {
    return payload;
  }

  const remaining = quotaRemaining();
  if (remaining <= 0) {
    throw new Error('Quota reached. Processing is paused until usage is reduced or the plan changes.');
  }

  const plan = activePlan();
  const flags = activeFlags();
  const runLimit = flags.bulkProcessing ? remaining : Math.min(remaining, plan.maxFilesPerRun);
  if (!payload.max_files || payload.max_files > runLimit) {
    payload.max_files = runLimit;
  }
  return payload;
}

function applyAccessControls() {
  const signedIn = isAuthenticated();
  const flags = activeFlags();
  const plan = activePlan();
  const dashboardControls = Array.from(document.querySelectorAll('button, input, select')).filter(
    (control) => !control.dataset.authControl,
  );

  dashboardControls.forEach((control) => {
    control.disabled = !signedIn;
  });

  const mediaFilter = el('#queryMedia');
  const statusFilter = el('#queryStatus');
  if (mediaFilter && statusFilter && signedIn && !flags.advancedFilters) {
    mediaFilter.value = 'all';
    statusFilter.value = 'all';
    mediaFilter.disabled = true;
    statusFilter.disabled = true;
  }

  const verifyButton = el('[data-action="verify"]');
  if (verifyButton) {
    verifyButton.disabled = !signedIn || !flags.verificationReports;
  }

  const maxFiles = el('#maxFiles');
  if (maxFiles && signedIn) {
    if (flags.bulkProcessing) {
      maxFiles.min = '0';
      maxFiles.max = String(plan.maxFilesPerRun);
    } else {
      maxFiles.min = '1';
      maxFiles.max = String(plan.maxFilesPerRun);
      const current = Number(maxFiles.value || 0);
      if (current === 0 || current > plan.maxFilesPerRun) {
        maxFiles.value = String(plan.maxFilesPerRun);
      }
    }
  }
}

async function refreshStatus() {
  if (!requireUserAuth()) {
    return null;
  }
  const payload = currentPayload();
  const params = new URLSearchParams({ source: payload.source, out: payload.out });
  const status = await requestJson(`/api/status?${params.toString()}`);
  renderStatus(status);
  return status;
}

async function runAction(action) {
  if (!requireUserAuth()) {
    return;
  }
  const payload = payloadForAction(action);
  const response = await requestJson('/api/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  renderLastRun(response);
  await refreshStatus();
}

async function refreshIndex() {
  if (!requireUserAuth()) {
    return;
  }
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
  if (!requireUserAuth()) {
    return;
  }
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
  document.body.addEventListener('submit', (event) => {
    if (event.target?.id !== 'userAuthForm') {
      return;
    }
    event.preventDefault();
    signIn().catch(onError);
  });

  document.body.addEventListener('click', (event) => {
    const target = event.target?.closest?.('[data-action]');
    const action = target?.dataset?.action;
    if (!action) {
      return;
    }
    event.preventDefault();
    if (action === 'auth-signout') {
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

async function loadDashboard() {
  if (!isAuthenticated()) {
    return;
  }
  await refreshStatus();
  await refreshIndex().catch(() => {});
}

async function bootstrap() {
  injectAuthUi();
  restoreAuthSession();
  bindActions();
  renderAuthDependentUi();
  await loadDashboard();
  setInterval(() => {
    if (isAuthenticated()) {
      refreshStatus().catch(() => {});
    }
  }, 8000);
}

window.addEventListener('load', () => {
  bootstrap().catch(onError);
});
