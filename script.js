// script.js - Updated to match your backend API
const API_BASE = window.location.origin; // Use same origin as served page
const ADMIN_EMAIL = 'timothymartinluther54@gmail.com';

const state = {
  currentUser: null,
  files: [],
  alerts: [],
  users: [],
  selectedFileId: null,
  selectedFileHistory: [],
  fileFilter: 'all', // 'all' | 'monitoring' | 'tampered'
  cloudBackups: [],
  stats: {
    files: 0,
    alerts: 0,
    safe_files: 0,
    tampered_files: 0,
  },
  poller: null,
};

// DOM Elements
const homePanel = document.getElementById('homePanel');
const authPanel = document.getElementById('authPanel');
const dashboardPanel = document.getElementById('dashboardPanel');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const verifyForm = document.getElementById('verifyForm');
const forgotPasswordForm = document.getElementById('forgotPasswordForm');
const resetPasswordForm = document.getElementById('resetPasswordForm');
const authToggle = document.querySelector('.auth-toggle');
const toggleButtons = document.querySelectorAll('.toggle-btn');
const homeLoginBtn = document.getElementById('homeLoginBtn');
const homeRegisterBtn = document.getElementById('homeRegisterBtn');
const backHomeBtn = document.getElementById('backHomeBtn');
const uploadForm = document.getElementById('uploadForm');
const fileInput = document.getElementById('fileInput');
const filePathInput = document.getElementById('filePathInput');
const browseBtn = document.getElementById('browseBtn');
const browseHint = document.getElementById('browseHint');
const fileTableBody = document.getElementById('fileTableBody');
const alertList = document.getElementById('alertList');
const userPanel = document.querySelector('.user-panel');
const userList = document.getElementById('userList');
const greetingText = document.getElementById('greetingText');
const safeCount = document.getElementById('safeCount');
const tamperedCount = document.getElementById('tamperedCount');
const alertCount = document.getElementById('alertCount');
const fileCount = document.getElementById('fileCount');
const logoutBtn = document.getElementById('logoutBtn');
const refreshBtn = document.getElementById('refreshBtn');
const simulateBtn = document.getElementById('simulateBtn');
const clearSelectionBtn = document.getElementById('clearSelectionBtn');
const selectedFileInfo = document.getElementById('selectedFileInfo');
const selectedFileName = document.getElementById('selectedFileName');
const selectedFileStatus = document.getElementById('selectedFileStatus');
const hash1 = document.getElementById('hash1');
const hash1Time = document.getElementById('hash1Time');
const hash2 = document.getElementById('hash2');
const hash2Time = document.getElementById('hash2Time');
const hash3 = document.getElementById('hash3');
const hash3Time = document.getElementById('hash3Time');

// ===== Helper Functions =====

const ALL_AUTH_FORMS = { login: loginForm, register: registerForm, verify: verifyForm, forgot: forgotPasswordForm, reset: resetPasswordForm };

function toggleAuthForm(formName) {
  const isPrimary = formName === 'login' || formName === 'register';
  authToggle.classList.toggle('hidden', !isPrimary);

  toggleButtons.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.form === formName);
  });

  Object.entries(ALL_AUTH_FORMS).forEach(([name, form]) => {
    form.classList.toggle('active', name === formName);
  });
}

function saveState() {
  localStorage.setItem('integrity-user', JSON.stringify(state.currentUser));
}

function loadState() {
  const storedUser = localStorage.getItem('integrity-user');
  if (storedUser) {
    try {
      state.currentUser = JSON.parse(storedUser);
    } catch (e) {
      state.currentUser = null;
    }
  }
}

function showHome() {
  homePanel.classList.remove('hidden');
  authPanel.classList.add('hidden');
  dashboardPanel.classList.add('hidden');
  stopPolling();
  clearFileSelection();
}

function showDashboard() {
  homePanel.classList.add('hidden');
  authPanel.classList.add('hidden');
  dashboardPanel.classList.remove('hidden');
  greetingText.textContent = `Welcome back, ${state.currentUser?.name || 'User'}`;
  loadDashboardData();
  refreshCloudPanel();
  startPolling();
}

function showAuth() {
  homePanel.classList.add('hidden');
  dashboardPanel.classList.add('hidden');
  authPanel.classList.remove('hidden');
  stopPolling();
  clearFileSelection();
}

function formatTime(date) {
  if (!date) return '—';
  try {
    const d = new Date(date);
    return d.toLocaleString();
  } catch (e) {
    return date;
  }
}

function isAdminUser() {
  return state.currentUser?.email?.toLowerCase() === ADMIN_EMAIL;
}

function getFileStatusClass(status) {
  switch (status?.toLowerCase()) {
    case 'tampered':
      return 'status-tampered';
    case 'monitoring':
      return 'status-monitoring';
    case 'safe':
      return 'status-safe';
    default:
      return 'status-monitoring';
  }
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function showToast(message, type = 'success') {
  const existingToast = document.getElementById('toast');
  if (existingToast) {
    existingToast.remove();
  }

  const toast = document.createElement('div');
  toast.id = 'toast';
  toast.className = `app-toast app-toast-${type}`;
  toast.setAttribute('role', 'alert');

  const icon = document.createElement('span');
  icon.className = 'app-toast-icon';
  icon.textContent = type === 'error' ? '⚠️' : '✅';

  const text = document.createElement('span');
  text.className = 'app-toast-text';
  text.textContent = message;

  const closeBtn = document.createElement('button');
  closeBtn.className = 'app-toast-close';
  closeBtn.setAttribute('aria-label', 'Dismiss');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', () => toast.remove());

  toast.appendChild(icon);
  toast.appendChild(text);
  toast.appendChild(closeBtn);
  document.body.appendChild(toast);

  setTimeout(() => {
    if (toast.parentNode) {
      toast.remove();
    }
  }, 5000);
}

function clearFileSelection() {
  state.selectedFileId = null;
  state.selectedFileHistory = [];
  if (selectedFileInfo) {
    selectedFileInfo.style.display = 'none';
  }
  if (selectedFileName) selectedFileName.textContent = 'File Name';
  if (selectedFileStatus) {
    selectedFileStatus.textContent = 'monitoring';
    selectedFileStatus.className = 'status-pill status-monitoring';
  }
  if (hash1) hash1.textContent = '—';
  if (hash1Time) hash1Time.textContent = '—';
  if (hash2) hash2.textContent = '—';
  if (hash2Time) hash2Time.textContent = '—';
  if (hash3) hash3.textContent = '—';
  if (hash3Time) hash3Time.textContent = '—';
}

async function loadFileHistory(fileId) {
  if (!fileId) return;

  try {
    const data = await apiRequest(`/api/files/${fileId}/history`);
    const file = data.file;
    const history = data.history || [];
    state.selectedFileHistory = history;

    if (file && selectedFileInfo) {
      selectedFileInfo.style.display = 'block';
      selectedFileName.textContent = file.name || 'File';
      selectedFileStatus.textContent = file.status || 'monitoring';
      selectedFileStatus.className = `status-pill ${getFileStatusClass(file.status)}`;

      const entries = history.slice(0, 3);
      const slots = [
        { el: hash1, timeEl: hash1Time },
        { el: hash2, timeEl: hash2Time },
        { el: hash3, timeEl: hash3Time },
      ];

      slots.forEach((slot, index) => {
        const entry = entries[index];
        if (entry) {
          slot.el.textContent = entry.hash_value || '—';
          slot.timeEl.textContent = formatTime(entry.timestamp);
        } else {
          slot.el.textContent = '—';
          slot.timeEl.textContent = '—';
        }
      });
    }
  } catch (error) {
    console.error('Failed to load file history:', error);
  }
}

function selectFile(fileId) {
  state.selectedFileId = fileId;
  const file = state.files.find((item) => item.id === fileId);
  if (file) {
    loadFileHistory(fileId);
  } else {
    clearFileSelection();
  }
}

// Add animation style
const style = document.createElement('style');
style.textContent = `
  @keyframes slideIn {
    from {
      transform: translateX(100px);
      opacity: 0;
    }
    to {
      transform: translateX(0);
      opacity: 1;
    }
  }
`;
document.head.appendChild(style);

// ===== API Functions =====

async function apiRequest(path, options = {}) {
  const headers = new Headers();
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok || (data.success === false)) {
    throw new Error(data.message || 'Request failed');
  }

  return data;
}

// ===== Dashboard Data Loading =====

async function loadDashboardData() {
  if (!state.currentUser?.id) return;

  try {
    // Load status/stats
    const statusData = await apiRequest(`/api/status?user_id=${state.currentUser.id}`);
    state.stats = statusData.stats || state.stats;

    // Load files
    const filesData = await apiRequest(`/api/files?user_id=${state.currentUser.id}`);
    state.files = filesData.files || [];

    // Load alerts
    const alertsData = await apiRequest(`/api/alerts?user_id=${state.currentUser.id}`);
    state.alerts = alertsData.alerts || [];

    // Load users (only for admin)
    if (isAdminUser()) {
      try {
        const usersData = await apiRequest(`/api/users?user_id=${state.currentUser.id}`);
        state.users = usersData.users || [];
      } catch (e) {
        state.users = [];
      }
    } else {
      state.users = [];
    }

    if (state.selectedFileId && !state.files.some((file) => file.id === state.selectedFileId)) {
      clearFileSelection();
    } else if (state.selectedFileId) {
      loadFileHistory(state.selectedFileId);
    }

    renderDashboard();
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
    // Don't show toast for polling errors to avoid spam
    if (!state.poller) {
      showToast('Failed to load dashboard data', 'error');
    }
  }
}

async function startMonitoringBackend() {
  try {
    await apiRequest('/api/monitor/start', { method: 'POST' });
  } catch (error) {
    console.error('Failed to start backend monitoring:', error);
  }
}

async function processFileUpload(filePath = '', file = null) {
  if (!state.currentUser?.id) {
    showToast('Please login first', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('user_id', state.currentUser.id);

  if (file) {
    formData.append('file', file);
  } else if (filePath) {
    formData.append('file_path', filePath);
  } else {
    showToast('Please select a file or provide a valid file path', 'error');
    return;
  }

  try {
    await apiRequest('/api/files', {
      method: 'POST',
      body: formData,
    });
    const label = file ? file.name : filePath;
    showToast(`Monitoring started for "${label}".`);
    await loadDashboardData();
  } catch (error) {
    console.error('File monitoring setup failed:', error);
    showToast(error.message || 'File monitoring setup failed', 'error');
  }
}

// ===== File and Alert Actions =====

async function deleteFile(fileId) {
  if (!confirm('Are you sure you want to delete this file?')) return;
  
  try {
    await apiRequest(`/api/files/${fileId}`, { method: 'DELETE' });
    showToast('File deleted successfully');
    await loadDashboardData();
  } catch (error) {
    console.error('Delete failed:', error);
    showToast(error.message || 'Delete failed', 'error');
  }
}

async function simulateChange(fileId) {
  try {
    await apiRequest(`/api/simulate/${fileId}`, { method: 'POST' });
    showToast('File modified for testing! Monitoring will detect changes.');
    await loadDashboardData();
  } catch (error) {
    console.error('Simulation failed:', error);
    showToast(error.message || 'Simulation failed', 'error');
  }
}

function setFileFilter(filter) {
  state.fileFilter = filter;
  renderDashboard();

  document.querySelectorAll('.stat-card').forEach((card) => card.classList.remove('active'));
  if (filter === 'monitoring') document.getElementById('statSafeCard')?.classList.add('active');
  if (filter === 'tampered') document.getElementById('statTamperedCard')?.classList.add('active');

  const dashboardBtn = document.getElementById('dashboardBtn');
  if (dashboardBtn) dashboardBtn.classList.toggle('active', filter === 'all');

  document.getElementById('filesTablePanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// --- Theme toggle (persisted, matches the script that runs before first paint) ---
const themeToggleBtn = document.getElementById('themeToggleBtn');
function applyThemeButtonIcon() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  if (themeToggleBtn) themeToggleBtn.textContent = isDark ? '☀️' : '🌙';
}
applyThemeButtonIcon();

if (themeToggleBtn) {
  themeToggleBtn.addEventListener('click', () => {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (isDark) {
      document.documentElement.removeAttribute('data-theme');
      localStorage.setItem('integrity-theme', 'light');
    } else {
      document.documentElement.setAttribute('data-theme', 'dark');
      localStorage.setItem('integrity-theme', 'dark');
    }
    applyThemeButtonIcon();
  });
}

// --- Dashboard / stat-card navigation ---
const dashboardBtnEl = document.getElementById('dashboardBtn');
if (dashboardBtnEl) {
  dashboardBtnEl.addEventListener('click', () => setFileFilter('all'));
}

document.getElementById('statSafeCard')?.addEventListener('click', () => setFileFilter('monitoring'));
document.getElementById('statTamperedCard')?.addEventListener('click', () => setFileFilter('tampered'));
document.getElementById('statFilesCard')?.addEventListener('click', () => setFileFilter('all'));
document.getElementById('statAlertsCard')?.addEventListener('click', () => {
  document.getElementById('alertsPanelHeader')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
});

async function resolveAlert(alertId) {
  try {
    const response = await apiRequest(`/api/alerts/${alertId}/resolve`, { method: 'POST' });
    showToast(response.message || 'Change accepted - monitoring continues.');
    await loadDashboardData();
  } catch (error) {
    console.error('Resolve failed:', error);
    showToast(error.message || 'Resolve failed', 'error');
  }
}

async function lockFile(fileId) {
  if (!confirm('Lock this file? Nothing outside this app will be able to open, edit, or delete it until you unlock it here.')) return;
  try {
    const response = await apiRequest(`/api/files/${fileId}/lock`, { method: 'POST' });
    showToast(response.message || 'File locked.');
    await loadDashboardData();
  } catch (error) {
    console.error('Lock failed:', error);
    showToast(error.message || 'Could not lock file', 'error');
  }
}

async function unlockFile(fileId) {
  try {
    const response = await apiRequest(`/api/files/${fileId}/unlock`, { method: 'POST' });
    showToast(response.message || 'File unlocked.');
    await loadDashboardData();
  } catch (error) {
    console.error('Unlock failed:', error);
    showToast(error.message || 'Could not unlock file', 'error');
  }
}

// ===== Secure Cloud Recovery Module =====

async function refreshCloudPanel() {
  if (!state.currentUser?.id) return;
  const { id: userId, email } = state.currentUser;

  const subscribeSection = document.getElementById('cloudSubscribeSection');
  const activeSection = document.getElementById('cloudActiveSection');
  const planLabel = document.getElementById('cloudPlanLabel');
  const connectSection = document.getElementById('cloudConnectSection');
  const backupSection = document.getElementById('cloudBackupSection');

  try {
    const statusData = await apiRequest(`/api/subscription/status?user_id=${userId}&email=${encodeURIComponent(email)}`);

    if (!statusData.active) {
      subscribeSection.classList.remove('hidden');
      activeSection.classList.add('hidden');
      return;
    }

    subscribeSection.classList.add('hidden');
    activeSection.classList.remove('hidden');
    planLabel.textContent = statusData.is_admin
      ? 'Admin plan: unlimited cloud access'
      : `Plan: ${statusData.plan} · renews/expires ${formatTime(statusData.expires_at)}`;

    const driveStatus = await apiRequest(`/api/cloud/google/status?user_id=${userId}`);
    if (driveStatus.connected) {
      connectSection.classList.add('hidden');
      backupSection.classList.remove('hidden');
      await refreshCloudBackupList();
      await refreshCloudQuota();
    } else {
      connectSection.classList.remove('hidden');
      backupSection.classList.add('hidden');
    }
  } catch (error) {
    console.error('Failed to refresh cloud panel:', error);
  }
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

async function refreshCloudQuota() {
  const quotaLabel = document.getElementById('cloudQuotaLabel');
  try {
    const quota = await apiRequest(`/api/cloud/google/quota?user_id=${state.currentUser.id}`);
    quotaLabel.textContent = quota.limit
      ? `Google Drive storage: ${formatBytes(quota.used)} of ${formatBytes(quota.limit)} used`
      : `Google Drive storage: ${formatBytes(quota.used)} used (unlimited plan)`;
  } catch (error) {
    quotaLabel.textContent = '';
  }
}

async function refreshCloudBackupList() {
  const listEl = document.getElementById('cloudBackupList');
  try {
    const data = await apiRequest(`/api/cloud/backups?user_id=${state.currentUser.id}`);
    const backups = data.backups || [];
    state.cloudBackups = backups;
    if (!backups.length) {
      listEl.innerHTML = '<li class="empty-state">No backups yet</li>';
      return;
    }
    listEl.innerHTML = backups.map((b) => `
      <li>
        <strong style="color: var(--text);">${b.original_name}</strong>
        <div style="color: var(--muted); font-size: 0.78rem;">Backed up ${formatTime(b.backed_up_at)}</div>
      </li>
    `).join('');
  } catch (error) {
    console.error('Failed to load cloud backups:', error);
  }
}

document.querySelectorAll('#cloudSubscribeSection [data-plan]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    try {
      const response = await apiRequest('/api/subscribe', {
        method: 'POST',
        body: JSON.stringify({
          user_id: state.currentUser.id,
          email: state.currentUser.email,
          plan: btn.dataset.plan,
        }),
      });
      showToast(response.message || 'Continue in your browser to complete payment.');
    } catch (error) {
      console.error('Subscribe failed:', error);
      showToast(error.message || 'Could not start payment', 'error');
    }
  });
});

document.getElementById('connectGoogleDriveBtn')?.addEventListener('click', async () => {
  try {
    const response = await apiRequest('/api/cloud/google/connect', {
      method: 'POST',
      body: JSON.stringify({ user_id: state.currentUser.id }),
    });
    showToast(response.message || 'Continue in your browser.');
  } catch (error) {
    console.error('Connect Google Drive failed:', error);
    showToast(error.message || 'Could not connect Google Drive', 'error');
  }
});

document.getElementById('backupFileBtn')?.addEventListener('click', async () => {
  if (!window.pywebview || !window.pywebview.api) {
    showToast('File picking requires the desktop app window.', 'error');
    return;
  }
  const filePath = await window.pywebview.api.pick_file();
  if (!filePath) {
    showToast('No file selected.');
    return;
  }
  try {
    showToast('Encrypting and uploading, please wait...');
    const response = await apiRequest('/api/cloud/backup', {
      method: 'POST',
      body: JSON.stringify({ user_id: state.currentUser.id, email: state.currentUser.email, file_path: filePath }),
    });
    showToast(response.message || 'File backed up successfully.');
    await refreshCloudBackupList();
    await refreshCloudQuota();
  } catch (error) {
    console.error('Backup failed:', error);
    showToast(error.message || 'Backup failed. Please try again.', 'error');
  }
});

// --- Password re-confirmation modal (required before retrieving files) ---
function requestPasswordConfirmation() {
  const overlay = document.getElementById('passwordConfirmOverlay');
  const input = document.getElementById('passwordConfirmInput');
  const submitBtn = document.getElementById('passwordConfirmSubmitBtn');
  const cancelBtn = document.getElementById('passwordConfirmCancelBtn');
  const forgotBtn = document.getElementById('passwordConfirmForgotBtn');

  input.value = '';
  overlay.classList.remove('hidden');
  input.focus();

  return new Promise((resolve) => {
    function cleanup(result) {
      overlay.classList.add('hidden');
      submitBtn.removeEventListener('click', onSubmit);
      cancelBtn.removeEventListener('click', onCancel);
      forgotBtn.removeEventListener('click', onForgot);
      resolve(result);
    }
    async function onSubmit() {
      const password = input.value;
      if (!password) return;
      try {
        await apiRequest('/api/auth/confirm-password', {
          method: 'POST',
          body: JSON.stringify({ email: state.currentUser.email, password }),
        });
        cleanup(true);
      } catch (error) {
        showToast(error.message || 'Incorrect password.', 'error');
      }
    }
    function onCancel() {
      cleanup(false);
    }
    function onForgot() {
      cleanup(false);
      showToast('Log out and use "Forgot password?" on the login screen to reset it.');
    }
    submitBtn.addEventListener('click', onSubmit);
    cancelBtn.addEventListener('click', onCancel);
    forgotBtn.addEventListener('click', onForgot);
  });
}

document.getElementById('retrieveFilesBtn')?.addEventListener('click', async () => {
  const confirmed = await requestPasswordConfirmation();
  if (!confirmed) return;
  openRetrieveModal();
});

function openRetrieveModal() {
  const overlay = document.getElementById('retrieveModalOverlay');
  const listEl = document.getElementById('retrieveFileList');
  const selectAll = document.getElementById('retrieveSelectAll');
  const backups = state.cloudBackups || [];

  if (!backups.length) {
    showToast('No backed up files to retrieve yet.');
    return;
  }

  listEl.innerHTML = backups.map((b) => `
    <li class="retrieve-item">
      <input type="checkbox" class="retrieve-checkbox" value="${b.id}" id="retrieve-${b.id}" />
      <label for="retrieve-${b.id}">${b.original_name}<br><small style="color: var(--muted);">Backed up ${formatTime(b.backed_up_at)}</small></label>
    </li>
  `).join('');

  selectAll.checked = false;
  selectAll.onchange = () => {
    document.querySelectorAll('.retrieve-checkbox').forEach((cb) => { cb.checked = selectAll.checked; });
  };

  overlay.classList.remove('hidden');
}

document.getElementById('retrieveCancelBtn')?.addEventListener('click', () => {
  document.getElementById('retrieveModalOverlay').classList.add('hidden');
});

document.getElementById('retrieveConfirmBtn')?.addEventListener('click', async () => {
  const selectedIds = Array.from(document.querySelectorAll('.retrieve-checkbox:checked')).map((cb) => Number(cb.value));
  if (!selectedIds.length) {
    showToast('Select at least one file.', 'error');
    return;
  }
  if (!window.pywebview || !window.pywebview.api) {
    showToast('File restore requires the desktop app window.', 'error');
    return;
  }
  const folder = await window.pywebview.api.pick_folder();
  if (!folder) return;

  document.getElementById('retrieveModalOverlay').classList.add('hidden');
  showToast(`Restoring ${selectedIds.length} file(s)...`);

  let successCount = 0;
  for (const backupId of selectedIds) {
    const backup = state.cloudBackups.find((b) => b.id === backupId);
    if (!backup) continue;
    const destinationPath = `${folder}\\${backup.original_name}`;
    try {
      await apiRequest('/api/cloud/restore', {
        method: 'POST',
        body: JSON.stringify({
          user_id: state.currentUser.id,
          email: state.currentUser.email,
          backup_id: backupId,
          destination_path: destinationPath,
        }),
      });
      successCount++;
    } catch (error) {
      console.error(`Restore failed for ${backup.original_name}:`, error);
      showToast(`Failed to restore ${backup.original_name}: ${error.message}`, 'error');
    }
  }

  showToast(`${successCount} of ${selectedIds.length} file(s) restored to ${folder}.`);
});

async function reverseFile(fileId) {
  if (!confirm('This will overwrite the current file with its last known-good version. Continue?')) return;

  try {
    const response = await apiRequest(`/api/files/${fileId}/reverse`, { method: 'POST' });
    showToast(response.message || 'File restored.');
    await loadDashboardData();
  } catch (error) {
    console.error('Reverse failed:', error);
    showToast(error.message || 'Reverse failed', 'error');
  }
}

// ===== Render Functions =====

function renderDashboard() {
  // Show/hide user panel based on admin status
  if (userPanel) {
    userPanel.classList.toggle('hidden', !isAdminUser());
  }

  // Update stats
  safeCount.textContent = state.stats.safe_files || 0;
  tamperedCount.textContent = state.stats.tampered_files || 0;
  alertCount.textContent = state.stats.alerts || 0;
  fileCount.textContent = state.stats.files || 0;

  // Render files table (respecting the active stat-card filter, if any)
  const filteredFiles = state.fileFilter === 'all'
    ? state.files
    : state.files.filter((file) => {
        const status = file.status || 'monitoring';
        return state.fileFilter === 'monitoring' ? status === 'monitoring' : status !== 'monitoring';
      });

  const filterIndicator = document.getElementById('fileFilterIndicator');
  if (state.fileFilter === 'all') {
    filterIndicator.classList.add('hidden');
  } else {
    filterIndicator.classList.remove('hidden');
    filterIndicator.innerHTML = `Showing: ${state.fileFilter === 'monitoring' ? 'Safe' : 'Tampered'} only <a href="#" onclick="event.preventDefault(); setFileFilter('all');" style="margin-left: 6px; text-decoration: underline;">Clear</a>`;
  }

  fileTableBody.innerHTML = '';
  if (!filteredFiles.length) {
    fileTableBody.innerHTML = `<tr><td colspan="5" class="empty-row">${state.files.length ? 'No files match this filter' : 'No files uploaded yet'}</td></tr>`;
  } else {
    filteredFiles.forEach((file) => {
      const hashToShow = file.current_hash || file.trusted_hash || '—';

      const row = document.createElement('tr');
      row.style.cursor = 'pointer';
      row.style.background = state.selectedFileId === file.id ? 'rgba(75, 123, 255, 0.08)' : '';
      row.addEventListener('click', () => {
        selectFile(file.id);
      });

      row.innerHTML = `
        <td>
          <strong>${file.name}</strong>${file.locked ? ' <span class="status-pill" style="background: rgba(90, 82, 72, 0.15); color: var(--text-secondary);">🔒 Locked</span>' : ''}<br />
          <small style="color: var(--muted); font-size: 0.75rem;">${file.path || ''}</small>
        </td>
        <td><code style="background: var(--surface-3); padding: 4px 8px; border-radius: 6px; font-size: 0.8rem;">${hashToShow.slice(0, 18)}${hashToShow.length > 18 ? '...' : ''}</code></td>
        <td>
          <span class="status-pill ${getFileStatusClass(file.status)}">${file.locked ? 'locked' : (file.status || 'monitoring')}</span>
        </td>
        <td>${formatTime(file.last_checked)}</td>
        <td>
          <div class="row-actions">
            ${file.status && file.status !== 'monitoring' && !file.locked ? `<button class="ghost-btn" style="padding: 6px 12px; font-size: 0.8rem; background: rgba(31, 190, 128, 0.1); color: var(--success);" onclick="event.stopPropagation(); reverseFile(${file.id})">Reverse</button>` : ''}
            ${file.locked
              ? `<button class="ghost-btn" style="padding: 6px 12px; font-size: 0.8rem; background: rgba(212, 163, 115, 0.15); color: var(--accent-2);" onclick="event.stopPropagation(); unlockFile(${file.id})">Unlock</button>`
              : `<button class="ghost-btn" style="padding: 6px 12px; font-size: 0.8rem;" onclick="event.stopPropagation(); lockFile(${file.id})">Lock</button>`}
            <button class="ghost-btn" style="padding: 6px 12px; font-size: 0.8rem;" onclick="event.stopPropagation(); simulateChange(${file.id})" ${file.locked ? 'disabled' : ''}>Simulate</button>
            <button class="ghost-btn" style="padding: 6px 12px; font-size: 0.8rem; background: rgba(255, 93, 115, 0.1); color: #ffb2bf;" onclick="event.stopPropagation(); deleteFile(${file.id})">Delete</button>
          </div>
        </td>
      `;
      fileTableBody.appendChild(row);
    });
  }

  // Render alerts
  alertList.innerHTML = '';
  if (!state.alerts.length) {
    alertList.innerHTML = '<li class="empty-state">No alerts yet</li>';
  } else {
    state.alerts.slice(0, 5).forEach((alert) => {
      const isResolved = alert.resolved || false;
      const item = document.createElement('li');
      item.style.cssText = `
        background: ${isResolved ? 'rgba(31, 190, 128, 0.08)' : 'rgba(255, 93, 115, 0.08)'};
        border-color: ${isResolved ? 'rgba(31, 190, 128, 0.15)' : 'rgba(255, 93, 115, 0.15)'};
        padding: 12px;
        border-radius: 8px;
        margin-bottom: 8px;
      `;
      item.innerHTML = `
        <div class="row-actions" style="justify-content: space-between; align-items: start; gap: 10px;">
          <div style="flex: 1; min-width: 140px;">
            <strong style="color: var(--text);">${alert.file_name}</strong>
            <div style="color: var(--muted); font-size: 0.85rem; margin-top: 4px;">
              ${isResolved ? '✅ Resolved' : '⚠️ Tampered'} at ${formatTime(alert.timestamp)}
            </div>
            <small style="color: var(--muted); font-size: 0.75rem;">
              ${alert.previous_hash ? alert.previous_hash.slice(0, 12) + '...' : '—'} → 
              ${alert.new_hash ? alert.new_hash.slice(0, 12) + '...' : '—'}
            </small>
            ${alert.os_username ? `
              <div style="color: var(--muted); font-size: 0.75rem; margin-top: 4px;">
                🖥️ ${alert.os_username}@${alert.hostname || 'unknown'}
                ${alert.session_type === 'remote'
                  ? ` · <span style="color: var(--danger);">Remote session${alert.remote_ip ? ' from ' + alert.remote_ip : ''}</span>`
                  : ' · Local session'}
              </div>
            ` : ''}
          </div>
          ${!isResolved ? `
            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
              <button class="ghost-btn" style="padding: 4px 12px; font-size: 0.8rem; background: rgba(31, 190, 128, 0.1); color: var(--success);" onclick="event.stopPropagation(); reverseFile(${alert.file_id})">Reverse</button>
              <button class="ghost-btn" style="padding: 4px 12px; font-size: 0.8rem; background: rgba(212, 163, 115, 0.15); color: var(--accent-2);" onclick="event.stopPropagation(); resolveAlert(${alert.id})">Resolve</button>
            </div>
          ` : ''}
        </div>
      `;
      alertList.appendChild(item);
    });
  }

  // Render users (admin only)
  if (userList) {
    userList.innerHTML = '';
    if (!state.users.length) {
      userList.innerHTML = '<li class="empty-state">No users found</li>';
    } else {
      state.users.forEach((user) => {
        const item = document.createElement('li');
        item.style.cssText = `
          background: rgba(75, 123, 255, 0.08);
          border-color: rgba(75, 123, 255, 0.15);
          padding: 12px;
          border-radius: 8px;
          margin-bottom: 8px;
        `;
        item.innerHTML = `
          <div>
            <strong style="color: var(--text);">${user.name}</strong>
            <div style="color: var(--muted); font-size: 0.85rem;">${user.email}</div>
            <small style="color: var(--muted); font-size: 0.75rem;">Joined ${formatTime(user.created_at)}</small>
          </div>
        `;
        userList.appendChild(item);
      });
    }
  }
}

// ===== Polling =====

function startPolling() {
  stopPolling();
  state.poller = setInterval(() => {
    loadDashboardData();
  }, 3000);
}

function stopPolling() {
  if (state.poller) {
    clearInterval(state.poller);
    state.poller = null;
  }
}

// ===== Event Listeners =====

// Login
loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;

  if (!email || !password) {
    showToast('Please enter both your email and password.', 'error');
    return;
  }
  if (!isValidEmail(email)) {
    showToast('That email address doesn\'t look valid. Please check it and try again.', 'error');
    return;
  }

  try {
    const response = await apiRequest('/api/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });

    state.currentUser = response.user;
    saveState();
    await startMonitoringBackend();
    showDashboard();
    showToast('Login successful! Welcome back.');
  } catch (error) {
    console.error('Login error:', error);
    showToast(error.message || 'Login failed. Please check your details and try again.', 'error');
  }
});

// Register
registerForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = document.getElementById('registerName').value.trim();
  const email = document.getElementById('registerEmail').value.trim();
  const password = document.getElementById('registerPassword').value;

  if (!name || !email || !password) {
    showToast('Please fill in your name, email, and password.', 'error');
    return;
  }
  if (!isValidEmail(email)) {
    showToast('That email address doesn\'t look valid. Please check it and try again.', 'error');
    return;
  }
  if (password.length < 6) {
    showToast('Your password needs to be at least 6 characters long.', 'error');
    return;
  }

  try {
    const response = await apiRequest('/api/register', {
      method: 'POST',
      body: JSON.stringify({ name, email, password }),
    });

    if (response.requires_email_confirmation) {
      showToast(response.message || 'Check your email for a verification code.', 'success');
      document.getElementById('verifyEmail').value = email;
      document.getElementById('verifyEmailLabel').textContent = email;
      toggleAuthForm('verify');
      registerForm.reset();
      return;
    }

    state.currentUser = response.user;
    saveState();
    await startMonitoringBackend();
    showDashboard();
    showToast('Registration successful! Welcome in.');
  } catch (error) {
    console.error('Registration error:', error);
    showToast(error.message || 'Registration failed', 'error');
  }
});

// Toggle auth forms
toggleButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    toggleAuthForm(btn.dataset.form);
  });
});

document.getElementById('showForgotPasswordBtn').addEventListener('click', () => {
  toggleAuthForm('forgot');
});
document.getElementById('backToLoginFromVerifyBtn').addEventListener('click', () => toggleAuthForm('login'));
document.getElementById('backToLoginFromForgotBtn').addEventListener('click', () => toggleAuthForm('login'));
document.getElementById('backToLoginFromResetBtn').addEventListener('click', () => toggleAuthForm('login'));

verifyForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const email = document.getElementById('verifyEmail').value.trim();
  const token = document.getElementById('verifyCode').value.trim();

  try {
    const response = await apiRequest('/api/verify-signup', {
      method: 'POST',
      body: JSON.stringify({ email, token }),
    });
    state.currentUser = response.user;
    saveState();
    await startMonitoringBackend();
    showDashboard();
    showToast('Email verified! Welcome in.');
    verifyForm.reset();
  } catch (error) {
    console.error('Verification error:', error);
    showToast(error.message || 'Verification failed', 'error');
  }
});

forgotPasswordForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const email = document.getElementById('forgotEmail').value.trim();

  try {
    const response = await apiRequest('/api/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
    showToast(response.message || 'Reset code sent.', 'success');
    document.getElementById('resetEmail').value = email;
    document.getElementById('resetEmailLabel').textContent = email;
    toggleAuthForm('reset');
    forgotPasswordForm.reset();
  } catch (error) {
    console.error('Forgot-password error:', error);
    showToast(error.message || 'Could not send reset code', 'error');
  }
});

resetPasswordForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const email = document.getElementById('resetEmail').value.trim();
  const token = document.getElementById('resetCode').value.trim();
  const newPassword = document.getElementById('resetNewPassword').value;

  try {
    const response = await apiRequest('/api/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, token, new_password: newPassword }),
    });
    showToast(response.message || 'Password updated. Please log in.', 'success');
    resetPasswordForm.reset();
    toggleAuthForm('login');
  } catch (error) {
    console.error('Reset-password error:', error);
    showToast(error.message || 'Could not reset password', 'error');
  }
});

// File monitoring setup
uploadForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const filePath = filePathInput.value.trim();
  const selectedFile = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;

  if (filePath) {
    await processFileUpload(filePath, null);
  } else if (selectedFile) {
    await processFileUpload('', selectedFile);
  } else {
    showToast('Please choose a file to monitor', 'error');
  }

  filePathInput.value = '';
  fileInput.value = '';
});

// Native OS file picker (pywebview) - returns the real absolute path,
// which is required for live tamper detection of the original file.
let pywebviewReady = false;
window.addEventListener('pywebviewready', () => {
  pywebviewReady = true;
  browseHint.classList.add('hidden');
});

if (browseBtn) {
  browseBtn.addEventListener('click', async () => {
    if (!pywebviewReady || !window.pywebview || !window.pywebview.api) {
      browseHint.classList.remove('hidden');
      return;
    }
    try {
      const path = await window.pywebview.api.pick_file();
      if (path) {
        filePathInput.value = path;
        fileInput.value = '';
      }
    } catch (error) {
      console.error('Native file picker failed:', error);
      browseHint.classList.remove('hidden');
    }
  });

  // If pywebview hasn't announced readiness shortly after load, assume
  // we're running in a plain browser (e.g. `python app.py` fallback mode)
  // and show the hint so the user knows to type the path manually.
  setTimeout(() => {
    if (!pywebviewReady) browseHint.classList.remove('hidden');
  }, 1500);
}

// Home page navigation
if (homeLoginBtn) {
  homeLoginBtn.addEventListener('click', () => {
    toggleAuthForm('login');
    showAuth();
  });
}

if (homeRegisterBtn) {
  homeRegisterBtn.addEventListener('click', () => {
    toggleAuthForm('register');
    showAuth();
  });
}

if (backHomeBtn) {
  backHomeBtn.addEventListener('click', () => {
    showHome();
  });
}

// Logout
logoutBtn.addEventListener('click', () => {
  state.currentUser = null;
  saveState();
  showHome();
  showToast('Logged out');
});

// Refresh
refreshBtn.addEventListener('click', () => {
  loadDashboardData();
  showToast('Dashboard refreshed');
});

// Clear selected file history
if (clearSelectionBtn) {
  clearSelectionBtn.addEventListener('click', () => {
    clearFileSelection();
  });
}

// Simulate button (global)
if (simulateBtn) {
  simulateBtn.addEventListener('click', () => {
    if (state.files.length > 0) {
      const fileId = state.files[0].id;
      simulateChange(fileId);
    } else {
      showToast('No files to simulate', 'error');
    }
  });
}

// ===== Initialization =====

// Check if user is already logged in
loadState();
if (state.currentUser) {
  showDashboard();
} else {
  showHome();
}

console.log('🔐 File Integrity Monitor initialized');
console.log('📊 Dashboard will auto-refresh every 3 seconds');
console.log('👤 Admin email:', ADMIN_EMAIL);

// Make functions globally accessible for inline onclick handlers
window.simulateChange = simulateChange;
window.deleteFile = deleteFile;
window.resolveAlert = resolveAlert;