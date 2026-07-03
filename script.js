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

function toggleAuthForm(formName) {
  toggleButtons.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.form === formName);
  });

  loginForm.classList.toggle('active', formName === 'login');
  registerForm.classList.toggle('active', formName === 'register');
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

function showToast(message, type = 'success') {
  // Remove existing toast if any
  const existingToast = document.getElementById('toast');
  if (existingToast) {
    existingToast.remove();
  }

  // Create toast element
  const toast = document.createElement('div');
  toast.id = 'toast';
  toast.style.cssText = `
    position: fixed;
    bottom: 30px;
    right: 30px;
    background: #0f1b36;
    color: #eef5ff;
    padding: 16px 24px;
    border-radius: 12px;
    border: 1px solid rgba(149, 179, 255, 0.1);
    box-shadow: 0 25px 50px rgba(0,0,0,0.35);
    z-index: 9999;
    max-width: 400px;
    font-family: 'Inter', sans-serif;
    font-size: 0.95rem;
    animation: slideIn 0.3s ease;
    border-left: 4px solid ${type === 'error' ? '#ff5d73' : '#1fbe80'};
  `;
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    if (toast.parentNode) {
      toast.remove();
    }
  }, 4000);
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

async function resolveAlert(alertId) {
  try {
    await apiRequest(`/api/alerts/${alertId}/resolve`, { method: 'POST' });
    showToast('Alert resolved');
    await loadDashboardData();
  } catch (error) {
    console.error('Resolve failed:', error);
    showToast(error.message || 'Resolve failed', 'error');
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

  // Render files table
  fileTableBody.innerHTML = '';
  if (!state.files.length) {
    fileTableBody.innerHTML = '<tr><td colspan="5" class="empty-row">No files uploaded yet</td></tr>';
  } else {
    state.files.forEach((file) => {
      const hashToShow = file.current_hash || file.trusted_hash || '—';

      const row = document.createElement('tr');
      row.style.cursor = 'pointer';
      row.style.background = state.selectedFileId === file.id ? 'rgba(75, 123, 255, 0.08)' : '';
      row.addEventListener('click', () => {
        selectFile(file.id);
      });

      row.innerHTML = `
        <td>
          <strong>${file.name}</strong><br />
          <small style="color: var(--muted); font-size: 0.75rem;">${file.path || ''}</small>
        </td>
        <td><code style="background: var(--surface-3); padding: 4px 8px; border-radius: 6px; font-size: 0.8rem;">${hashToShow.slice(0, 18)}${hashToShow.length > 18 ? '...' : ''}</code></td>
        <td>
          <span class="status-pill ${getFileStatusClass(file.status)}">${file.status || 'monitoring'}</span>
        </td>
        <td>${formatTime(file.last_checked)}</td>
        <td>
          <div class="row-actions">
            <button class="ghost-btn" style="padding: 6px 12px; font-size: 0.8rem;" onclick="event.stopPropagation(); simulateChange(${file.id})">Simulate</button>
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
          </div>
          ${!isResolved ? `<button class="ghost-btn" style="padding: 4px 12px; font-size: 0.8rem; background: rgba(31, 190, 128, 0.1); color: var(--success);" onclick="event.stopPropagation(); resolveAlert(${alert.id})">Resolve</button>` : ''}
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
    showToast('Please fill in all fields', 'error');
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
    showToast('Login successful!');
  } catch (error) {
    console.error('Login error:', error);
    showToast(error.message || 'Login failed', 'error');
  }
});

// Register
registerForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = document.getElementById('registerName').value.trim();
  const email = document.getElementById('registerEmail').value.trim();
  const password = document.getElementById('registerPassword').value;

  if (!name || !email || !password) {
    showToast('Please fill in all fields', 'error');
    return;
  }

  try {
    const response = await apiRequest('/api/register', {
      method: 'POST',
      body: JSON.stringify({ name, email, password }),
    });

    state.currentUser = response.user;
    saveState();
    await startMonitoringBackend();
    showDashboard();
    showToast('Registration successful!');
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