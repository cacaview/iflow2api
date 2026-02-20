/**
 * iFlow2API 管理后台 JavaScript
 */

// API 基础路径
const API_BASE = '/admin';

// 全局状态
const state = {
    token: localStorage.getItem('admin_token'),
    currentUser: null,
    ws: null,
    settings: {},
    refreshInterval: null,
};

// ==================== 工具函数 ====================

/**
 * 显示 Toast 通知
 */
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * 发送 API 请求
 */
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };

    if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }

    try {
        const response = await fetch(url, {
            ...options,
            headers,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || '请求失败');
        }

        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

/**
 * 格式化时间
 */
function formatUptime(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

/**
 * 格式化日期时间
 */
function formatDateTime(isoString) {
    if (!isoString) return '--';
    const date = new Date(isoString);
    return date.toLocaleString('zh-CN');
}

// ==================== 认证相关 ====================

/**
 * 检查登录状态
 */
async function checkAuth() {
    if (!state.token) {
        showLoginPage();
        return false;
    }

    try {
        // 获取状态来验证 token
        await apiRequest('/status');
        showMainPage();
        return true;
    } catch (error) {
        localStorage.removeItem('admin_token');
        state.token = null;
        showLoginPage();
        return false;
    }
}

/**
 * 检查是否需要初始化
 */
async function checkSetup() {
    try {
        const data = await apiRequest('/check-setup');
        const hint = document.getElementById('login-hint');
        if (data.needs_setup) {
            hint.textContent = '首次使用，请设置管理员账户';
        } else {
            hint.textContent = '';
        }
    } catch (error) {
        console.error('Check setup error:', error);
    }
}

/**
 * 登录
 */
async function login(username, password) {
    try {
        const data = await apiRequest('/login', {
            method: 'POST',
            body: JSON.stringify({ username, password }),
        });

        state.token = data.token;
        localStorage.setItem('admin_token', data.token);
        state.currentUser = username;

        showToast(data.message, 'success');
        showMainPage();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * 登出
 */
async function logout() {
    try {
        await apiRequest('/logout', { method: 'POST' });
    } catch (error) {
        console.error('Logout error:', error);
    }

    localStorage.removeItem('admin_token');
    state.token = null;
    state.currentUser = null;

    if (state.ws) {
        state.ws.close();
        state.ws = null;
    }

    if (state.refreshInterval) {
        clearInterval(state.refreshInterval);
        state.refreshInterval = null;
    }

    showLoginPage();
    showToast('已退出登录', 'info');
}

// ==================== 页面切换 ====================

function showLoginPage() {
    document.getElementById('login-page').classList.add('active');
    document.getElementById('main-page').classList.remove('active');
    checkSetup();
}

function showMainPage() {
    document.getElementById('login-page').classList.remove('active');
    document.getElementById('main-page').classList.add('active');

    // 初始化数据
    loadStatus();
    loadSettings();
    loadUsers();

    // 连接 WebSocket
    connectWebSocket();

    // 启动定时刷新
    startAutoRefresh();
}

function showSection(sectionId) {
    // 隐藏所有区块
    document.querySelectorAll('.section').forEach(section => {
        section.classList.remove('active');
    });

    // 显示目标区块
    document.getElementById(`${sectionId}-section`).classList.add('active');

    // 更新导航
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.page === sectionId) {
            item.classList.add('active');
        }
    });

    // 更新标题
    const titles = {
        dashboard: '仪表盘',
        settings: '设置',
        users: '用户管理',
        logs: '日志',
    };
    document.getElementById('page-title').textContent = titles[sectionId] || sectionId;
}

// ==================== 数据加载 ====================

/**
 * 加载系统状态
 */
async function loadStatus() {
    try {
        const data = await apiRequest('/status');

        // 更新服务器状态
        const statusBadge = document.getElementById('server-status');
        statusBadge.className = `status-badge ${data.server.state}`;
        statusBadge.textContent = {
            stopped: '已停止',
            running: '运行中',
            starting: '启动中',
            stopping: '停止中',
            error: '错误',
        }[data.server.state] || data.server.state;

        // 更新错误消息
        document.getElementById('server-error').textContent = data.server.error_message || '';

        // 更新按钮状态
        const isRunning = data.server.state === 'running';
        document.getElementById('start-server-btn').disabled = isRunning;
        document.getElementById('stop-server-btn').disabled = !isRunning;
        document.getElementById('restart-server-btn').disabled = !isRunning;

        // 更新运行时间
        document.getElementById('uptime').textContent = formatUptime(data.process.uptime);

        // 更新 WebSocket 连接数
        document.getElementById('ws-connections').textContent = data.connections.websocket_count;

        // 更新系统信息
        document.getElementById('system-platform').textContent = data.system.platform;
        document.getElementById('system-arch').textContent = data.system.architecture;
        document.getElementById('python-version').textContent = data.system.python_version.split(' ')[0];
        document.getElementById('start-time').textContent = formatDateTime(data.process.start_time);

    } catch (error) {
        console.error('Load status error:', error);
    }
}

/**
 * 加载性能指标
 */
async function loadMetrics() {
    try {
        const data = await apiRequest('/metrics');

        // 更新请求统计
        if (data.rate_limit) {
            document.getElementById('requests-minute').textContent = data.rate_limit.requests_per_minute || 0;
            document.getElementById('requests-hour').textContent = data.rate_limit.requests_per_hour || 0;
            document.getElementById('requests-day').textContent = data.rate_limit.requests_per_day || 0;
        }
    } catch (error) {
        console.error('Load metrics error:', error);
    }
}

/**
 * 加载设置
 */
async function loadSettings() {
    try {
        const data = await apiRequest('/settings');
        state.settings = data;

        // 填充 iFlow 配置
        document.getElementById('setting-api-key').value = data.api_key || '';
        document.getElementById('setting-base-url').value = data.base_url || '';
        
        // 填充服务器配置
        document.getElementById('setting-host').value = data.host || '';
        document.getElementById('setting-port').value = data.port || 28000;
        
        // 填充启动设置
        document.getElementById('setting-auto-start').checked = data.auto_start || false;
        document.getElementById('setting-start-minimized').checked = data.start_minimized || false;
        document.getElementById('setting-minimize-to-tray').checked = data.close_action === 'minimize_to_tray';
        document.getElementById('setting-auto-run-server').checked = data.auto_run_server || false;
        
        // 填充界面设置
        document.getElementById('setting-theme').value = data.theme_mode || 'system';
        document.getElementById('setting-language').value = data.language || 'zh';
        
        // 填充内容处理设置
        document.getElementById('setting-preserve-reasoning').checked = data.preserve_reasoning_content || false;
        
        // 填充上游 API 设置
        document.getElementById('setting-api-concurrency').value = data.api_concurrency || 1;
        
        // 填充安全认证设置
        document.getElementById('setting-custom-api-key').value = data.custom_api_key || '';
        document.getElementById('setting-custom-auth-header').value = data.custom_auth_header || '';

    } catch (error) {
        console.error('Load settings error:', error);
    }
}

/**
 * 保存设置
 */
async function saveSettings() {
    const settings = {
        // iFlow 配置
        api_key: document.getElementById('setting-api-key').value,
        base_url: document.getElementById('setting-base-url').value,
        // 服务器配置
        host: document.getElementById('setting-host').value,
        port: parseInt(document.getElementById('setting-port').value),
        // 启动设置
        auto_start: document.getElementById('setting-auto-start').checked,
        start_minimized: document.getElementById('setting-start-minimized').checked,
        close_action: document.getElementById('setting-minimize-to-tray').checked ? 'minimize_to_tray' : 'exit',
        auto_run_server: document.getElementById('setting-auto-run-server').checked,
        // 界面设置
        theme_mode: document.getElementById('setting-theme').value,
        language: document.getElementById('setting-language').value,
        // 内容处理设置
        preserve_reasoning_content: document.getElementById('setting-preserve-reasoning').checked,
        // 上游 API 设置
        api_concurrency: parseInt(document.getElementById('setting-api-concurrency').value) || 1,
        // 安全认证设置
        custom_api_key: document.getElementById('setting-custom-api-key').value,
        custom_auth_header: document.getElementById('setting-custom-auth-header').value,
    };

    try {
        await apiRequest('/settings', {
            method: 'PUT',
            body: JSON.stringify(settings),
        });
        showToast('设置已保存', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * 从 iFlow CLI 导入配置
 */
async function importFromCli() {
    try {
        const data = await apiRequest('/import-from-cli', { method: 'POST' });
        showToast(data.message, 'success');
        // 更新表单
        document.getElementById('setting-api-key').value = data.api_key || '';
        document.getElementById('setting-base-url').value = data.base_url || '';
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * OAuth 登录
 */
let _oauthMessageHandler = null;

async function oauthLogin() {
    try {
        // 获取 OAuth URL
        const data = await apiRequest('/oauth/url');
        const authUrl = data.auth_url;
        
        // 打开新窗口进行 OAuth 登录
        const width = 600;
        const height = 700;
        const left = (window.innerWidth - width) / 2;
        const top = (window.innerHeight - height) / 2;
        
        const oauthWindow = window.open(
            authUrl,
            'iFlow OAuth',
            `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no`
        );
        
        // 移除之前的监听器（避免重复添加）
        if (_oauthMessageHandler) {
            window.removeEventListener('message', _oauthMessageHandler);
        }
        
        // 创建新的 OAuth 回调消息监听器
        _oauthMessageHandler = async (event) => {
            if (event.data && event.data.type === 'oauth_callback') {
                const code = event.data.code;
                if (code) {
                    try {
                        const result = await apiRequest('/oauth/callback', {
                            method: 'POST',
                            body: JSON.stringify({ code }),
                        });
                        showToast(result.message, 'success');
                        // 更新表单
                        document.getElementById('setting-api-key').value = result.api_key || '';
                    } catch (error) {
                        showToast(error.message, 'error');
                    }
                }
                // 处理完成后移除监听器
                window.removeEventListener('message', _oauthMessageHandler);
                _oauthMessageHandler = null;
            }
        };
        
        window.addEventListener('message', _oauthMessageHandler);
        
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * 加载用户列表
 */
async function loadUsers() {
    try {
        const users = await apiRequest('/users');
        const tbody = document.querySelector('#users-table tbody');
        tbody.innerHTML = '';

        users.forEach(user => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${user.username}</td>
                <td>${formatDateTime(user.created_at)}</td>
                <td>${formatDateTime(user.last_login)}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="deleteUser('${user.username}')">删除</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (error) {
        console.error('Load users error:', error);
    }
}

/**
 * 添加用户
 */
async function addUser(username, password) {
    try {
        await apiRequest('/users', {
            method: 'POST',
            body: JSON.stringify({ username, password }),
        });
        showToast('用户已添加', 'success');
        loadUsers();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * 删除用户
 */
async function deleteUser(username) {
    if (!confirm(`确定要删除用户 "${username}" 吗？`)) {
        return;
    }

    try {
        await apiRequest(`/users/${username}`, { method: 'DELETE' });
        showToast('用户已删除', 'success');
        loadUsers();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * 修改密码
 */
async function changePassword(oldPassword, newPassword) {
    try {
        await apiRequest('/change-password', {
            method: 'POST',
            body: JSON.stringify({
                old_password: oldPassword,
                new_password: newPassword,
            }),
        });
        showToast('密码已修改', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * 加载日志
 */
async function loadLogs() {
    try {
        const data = await apiRequest('/logs?lines=200');
        const logContent = document.getElementById('log-content');
        logContent.textContent = data.logs.join('\n') || '暂无日志';
    } catch (error) {
        document.getElementById('log-content').textContent = '加载日志失败: ' + error.message;
    }
}

// ==================== 服务器控制 ====================

async function startServer() {
    try {
        await apiRequest('/server/start', { method: 'POST' });
        showToast('服务器已启动', 'success');
        loadStatus();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function stopServer() {
    try {
        await apiRequest('/server/stop', { method: 'POST' });
        showToast('服务器已停止', 'success');
        loadStatus();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function restartServer() {
    try {
        await apiRequest('/server/restart', { method: 'POST' });
        showToast('服务器已重启', 'success');
        loadStatus();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ==================== WebSocket ====================

function connectWebSocket() {
    if (state.ws) {
        state.ws.close();
    }

    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    // 在 URL 中添加 token 查询参数（后端要求在握手阶段验证）
    const wsUrl = `${wsProtocol}//${location.host}${API_BASE}/ws?token=${encodeURIComponent(state.token)}`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        console.log('WebSocket connected');
        // 连接已通过 URL 参数认证，无需再发送 auth 消息
    };

    state.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };

    state.ws.onclose = () => {
        console.log('WebSocket disconnected');
        // 5秒后重连
        setTimeout(connectWebSocket, 5000);
    };

    state.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'status':
            // 更新状态
            break;
        case 'log':
            // 追加日志
            const logContent = document.getElementById('log-content');
            if (logContent && data.data) {
                logContent.textContent += `\n[${data.data.level}] ${data.data.message}`;
            }
            break;
        case 'settings_updated':
            showToast('设置已更新', 'info');
            loadSettings();
            break;
        case 'pong':
            // 心跳响应
            break;
    }
}

// ==================== 自动刷新 ====================

function startAutoRefresh() {
    if (state.refreshInterval) {
        clearInterval(state.refreshInterval);
    }

    state.refreshInterval = setInterval(() => {
        loadStatus();
        loadMetrics();
    }, 5000);
}

// ==================== 事件绑定 ====================

document.addEventListener('DOMContentLoaded', () => {
    // 登录表单
    document.getElementById('login-form').addEventListener('submit', (e) => {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        login(username, password);
    });

    // 登出按钮
    document.getElementById('logout-btn').addEventListener('click', logout);

    // 导航切换
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            showSection(page);

            // 加载对应数据
            if (page === 'logs') {
                loadLogs();
            }
        });
    });

    // 服务器控制按钮
    document.getElementById('start-server-btn').addEventListener('click', startServer);
    document.getElementById('stop-server-btn').addEventListener('click', stopServer);
    document.getElementById('restart-server-btn').addEventListener('click', restartServer);

    // 设置保存
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
    document.getElementById('reset-settings-btn').addEventListener('click', loadSettings);

    // iFlow 配置按钮
    document.getElementById('import-cli-btn').addEventListener('click', importFromCli);
    document.getElementById('oauth-login-btn').addEventListener('click', oauthLogin);

    // 添加用户表单
    document.getElementById('add-user-form').addEventListener('submit', (e) => {
        e.preventDefault();
        const username = document.getElementById('new-username').value;
        const password = document.getElementById('new-password').value;
        addUser(username, password);
        e.target.reset();
    });

    // 修改密码表单
    document.getElementById('change-password-form').addEventListener('submit', (e) => {
        e.preventDefault();
        const oldPassword = document.getElementById('old-password').value;
        const newPassword = document.getElementById('new-password-change').value;
        changePassword(oldPassword, newPassword);
        e.target.reset();
    });

    // 日志刷新
    document.getElementById('refresh-logs-btn').addEventListener('click', loadLogs);
    document.getElementById('clear-logs-btn').addEventListener('click', () => {
        document.getElementById('log-content').textContent = '';
    });

    // 检查认证状态
    checkAuth();
});
