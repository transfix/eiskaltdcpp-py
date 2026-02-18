"""
Web dashboard for eiskaltdcpp-py.

Serves a single-page dashboard at ``/dashboard`` with:
- Login page
- Main dashboard with real-time stats
- Hub management (connect/disconnect/users)
- Live chat viewer
- Search with live results
- Download queue management
- Share management
- Settings editor
- Real-time event log

Inspired by the Verlihub dashboard design: Bulma CSS, dark/light theme,
Font Awesome icons, stat cards, WebSocket-driven updates.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>eiskaltdcpp-py Dashboard</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.9.4/css/bulma.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
:root {
    --dc-primary: #00d1b2;
    --dc-primary-dark: #00b89c;
    --dc-dark-bg: #0f1923;
    --dc-dark-card: #162231;
    --dc-dark-card-alt: #1a2a3a;
    --dc-dark-text: #e4e4e4;
    --dc-dark-border: #2a3a4a;
    --dc-danger: #f14668;
    --dc-success: #48c774;
    --dc-warning: #ffdd57;
    --dc-info: #3e8ed0;
}
/* Dark theme (default) */
[data-theme="dark"] body { background: var(--dc-dark-bg); color: var(--dc-dark-text); }
[data-theme="dark"] .navbar { background: var(--dc-dark-card); border-bottom: 1px solid var(--dc-dark-border); }
[data-theme="dark"] .navbar-item, [data-theme="dark"] .navbar-link { color: var(--dc-dark-text); }
[data-theme="dark"] .navbar-item:hover { background: var(--dc-dark-card-alt); }
[data-theme="dark"] .box, [data-theme="dark"] .card { background: var(--dc-dark-card); color: var(--dc-dark-text); border: 1px solid var(--dc-dark-border); }
[data-theme="dark"] .table { background: var(--dc-dark-card); color: var(--dc-dark-text); }
[data-theme="dark"] .table th { color: #aab; border-color: var(--dc-dark-border); }
[data-theme="dark"] .table td { border-color: var(--dc-dark-border); }
[data-theme="dark"] .table.is-hoverable tbody tr:hover { background: var(--dc-dark-card-alt); }
[data-theme="dark"] .input, [data-theme="dark"] .textarea, [data-theme="dark"] .select select {
    background: #0a1421; border-color: var(--dc-dark-border); color: var(--dc-dark-text);
}
[data-theme="dark"] .title, [data-theme="dark"] .subtitle, [data-theme="dark"] .label { color: var(--dc-dark-text); }
[data-theme="dark"] .modal-card-head, [data-theme="dark"] .modal-card-foot { background: var(--dc-dark-card); border-color: var(--dc-dark-border); }
[data-theme="dark"] .modal-card-body { background: var(--dc-dark-bg); color: var(--dc-dark-text); }
[data-theme="dark"] .modal-card-title { color: var(--dc-dark-text); }
[data-theme="dark"] .tabs a { color: var(--dc-dark-text); border-color: var(--dc-dark-border); }
[data-theme="dark"] .tabs li.is-active a { color: var(--dc-primary); border-color: var(--dc-primary); }
[data-theme="dark"] .footer { background: var(--dc-dark-card); color: #889; }
[data-theme="dark"] .notification { border: 1px solid var(--dc-dark-border); }

/* Light overrides */
[data-theme="light"] body { background: #f5f7fa; }

/* Common */
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; min-height: 100vh; }
.navbar { position: fixed; top: 0; left: 0; right: 0; z-index: 100; height: 52px; }
.main-content { margin-top: 60px; padding: 1rem 1.5rem; }
.stat-card { text-align: center; padding: 1.25rem; }
.stat-card .stat-value { font-size: 2rem; font-weight: 700; color: var(--dc-primary); line-height: 1.2; }
.stat-card .stat-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.7; margin-top: 0.25rem; }
.status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
.status-dot.online { background: var(--dc-success); box-shadow: 0 0 6px var(--dc-success); }
.status-dot.offline { background: var(--dc-danger); }
.chat-log { font-family: 'Consolas', 'Monaco', 'Fira Code', monospace; font-size: 0.85rem; max-height: 400px; overflow-y: auto;
    padding: 0.75rem; border-radius: 4px; }
[data-theme="dark"] .chat-log { background: #0a1421; }
[data-theme="light"] .chat-log { background: #f0f0f0; }
.chat-line { padding: 2px 0; word-break: break-word; }
.chat-line .nick { color: var(--dc-primary); font-weight: 600; }
.chat-line .timestamp { color: #6a9955; font-size: 0.8em; margin-right: 6px; }
.event-log { font-family: 'Consolas', monospace; font-size: 0.8rem; max-height: 300px; overflow-y: auto; padding: 0.5rem; }
[data-theme="dark"] .event-log { background: #0a1421; border: 1px solid var(--dc-dark-border); border-radius: 4px; }
.event-entry { padding: 2px 4px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.event-entry .ev-time { color: #6a9955; margin-right: 8px; }
.event-entry .ev-type { font-weight: 600; margin-right: 6px; }
.tab-content { display: none; }
.tab-content.is-active { display: block; }
.ws-badge { font-size: 0.7rem; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }
.ws-badge.connected { background: var(--dc-success); color: #fff; }
.ws-badge.disconnected { background: var(--dc-danger); color: #fff; }
.fade-in { animation: fadeIn 0.3s ease-in; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.sr-item { padding: 0.5rem; border-bottom: 1px solid var(--dc-dark-border); }
.sr-item:hover { background: var(--dc-dark-card-alt); }
.hero-stats { padding: 1rem 0; }
#login-page { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
#app-page { display: none; }
.table-container { overflow-x: auto; }
</style>
</head>
<body>

<!-- ===== LOGIN PAGE ===== -->
<div id="login-page">
<div class="column is-4">
<div class="box" style="max-width:400px;margin:auto;">
    <div class="has-text-centered mb-4">
        <span class="icon is-large has-text-primary"><i class="fas fa-network-wired fa-3x"></i></span>
        <h1 class="title is-4 mt-3">eiskaltdcpp-py</h1>
        <p class="subtitle is-6" style="opacity:0.7;">Dashboard Login</p>
    </div>
    <div id="login-error" class="notification is-danger is-light" style="display:none;"></div>
    <div class="field">
        <label class="label">Username</label>
        <div class="control has-icons-left">
            <input class="input" type="text" id="login-user" placeholder="admin" autofocus>
            <span class="icon is-small is-left"><i class="fas fa-user"></i></span>
        </div>
    </div>
    <div class="field">
        <label class="label">Password</label>
        <div class="control has-icons-left">
            <input class="input" type="password" id="login-pass" placeholder="Password">
            <span class="icon is-small is-left"><i class="fas fa-lock"></i></span>
        </div>
    </div>
    <button class="button is-primary is-fullwidth mt-4" onclick="doLogin()">
        <span class="icon"><i class="fas fa-sign-in-alt"></i></span><span>Login</span>
    </button>
</div>
</div>
</div>

<!-- ===== MAIN APP ===== -->
<div id="app-page">

<!-- Navbar -->
<nav class="navbar" role="navigation">
<div class="navbar-brand">
    <a class="navbar-item" style="font-weight:700;">
        <span class="icon has-text-primary mr-2"><i class="fas fa-network-wired"></i></span>
        eiskaltdcpp-py
        <span id="ws-status" class="ws-badge disconnected">WS</span>
    </a>
</div>
<div class="navbar-menu is-active">
    <div class="navbar-start">
        <a class="navbar-item" onclick="showTab('dashboard')"><span class="icon"><i class="fas fa-tachometer-alt"></i></span><span>Dashboard</span></a>
        <a class="navbar-item" onclick="showTab('hubs')"><span class="icon"><i class="fas fa-server"></i></span><span>Hubs</span></a>
        <a class="navbar-item" onclick="showTab('chat')"><span class="icon"><i class="fas fa-comments"></i></span><span>Chat</span></a>
        <a class="navbar-item" onclick="showTab('search')"><span class="icon"><i class="fas fa-search"></i></span><span>Search</span></a>
        <a class="navbar-item" onclick="showTab('queue')"><span class="icon"><i class="fas fa-download"></i></span><span>Queue</span></a>
        <a class="navbar-item" onclick="showTab('shares')"><span class="icon"><i class="fas fa-folder-open"></i></span><span>Shares</span></a>
        <a class="navbar-item" onclick="showTab('settings')"><span class="icon"><i class="fas fa-cog"></i></span><span>Settings</span></a>
    </div>
    <div class="navbar-end">
        <a class="navbar-item" onclick="toggleTheme()" title="Toggle theme"><span class="icon"><i class="fas fa-moon" id="theme-icon"></i></span></a>
        <div class="navbar-item has-dropdown is-hoverable">
            <a class="navbar-link"><span class="icon"><i class="fas fa-user-circle"></i></span><span id="nav-username">admin</span></a>
            <div class="navbar-dropdown is-right">
                <a class="navbar-item" onclick="doShutdown()"><span class="icon"><i class="fas fa-power-off"></i></span><span>Shutdown Server</span></a>
                <hr class="navbar-divider">
                <a class="navbar-item" onclick="doLogout()"><span class="icon"><i class="fas fa-sign-out-alt"></i></span><span>Logout</span></a>
            </div>
        </div>
    </div>
</div>
</nav>

<div class="main-content">

<!-- ===== DASHBOARD TAB ===== -->
<div id="tab-dashboard" class="tab-content is-active">
    <div class="columns is-multiline">
        <div class="column is-3"><div class="box stat-card"><div class="stat-value" id="stat-hubs">0</div><div class="stat-label">Connected Hubs</div></div></div>
        <div class="column is-3"><div class="box stat-card"><div class="stat-value" id="stat-share">0 B</div><div class="stat-label">Total Share</div></div></div>
        <div class="column is-3"><div class="box stat-card"><div class="stat-value" id="stat-queue">0</div><div class="stat-label">Queue Items</div></div></div>
        <div class="column is-3"><div class="box stat-card"><div class="stat-value" id="stat-uptime">0s</div><div class="stat-label">Uptime</div></div></div>
    </div>
    <div class="columns">
        <div class="column is-4"><div class="box stat-card"><div class="stat-value" id="stat-dl-speed">0 B/s</div><div class="stat-label">Download Speed</div></div></div>
        <div class="column is-4"><div class="box stat-card"><div class="stat-value" id="stat-ul-speed">0 B/s</div><div class="stat-label">Upload Speed</div></div></div>
        <div class="column is-4"><div class="box stat-card"><div class="stat-value" id="stat-files">0</div><div class="stat-label">Shared Files</div></div></div>
    </div>
    <div class="columns">
        <div class="column is-7">
            <div class="box">
                <h3 class="title is-5"><span class="icon"><i class="fas fa-server"></i></span> Connected Hubs</h3>
                <div class="table-container">
                <table class="table is-fullwidth is-striped is-hoverable is-narrow">
                    <thead><tr><th>URL</th><th>Name</th><th>Users</th><th>Status</th></tr></thead>
                    <tbody id="dash-hubs-table"></tbody>
                </table>
                </div>
            </div>
        </div>
        <div class="column is-5">
            <div class="box">
                <h3 class="title is-5"><span class="icon"><i class="fas fa-stream"></i></span> Live Events</h3>
                <div class="event-log" id="event-log"></div>
            </div>
        </div>
    </div>
</div>

<!-- ===== HUBS TAB ===== -->
<div id="tab-hubs" class="tab-content">
    <div class="box">
        <h3 class="title is-5">Connect to Hub</h3>
        <div class="field has-addons">
            <div class="control is-expanded"><input class="input" id="hub-url-input" placeholder="dchub://hub.example.com:411"></div>
            <div class="control"><button class="button is-primary" onclick="connectHub()"><span class="icon"><i class="fas fa-plug"></i></span><span>Connect</span></button></div>
        </div>
    </div>
    <div class="box">
        <h3 class="title is-5">Connected Hubs</h3>
        <table class="table is-fullwidth is-striped is-hoverable">
            <thead><tr><th>URL</th><th>Name</th><th>Users</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody id="hubs-table"></tbody>
        </table>
    </div>
    <div class="box" id="hub-users-box" style="display:none;">
        <h3 class="title is-5"><span class="icon"><i class="fas fa-users"></i></span> Users on <span id="hub-users-title"></span></h3>
        <table class="table is-fullwidth is-striped is-hoverable is-narrow">
            <thead><tr><th>Nick</th><th>Share</th><th>Description</th><th>Tag</th></tr></thead>
            <tbody id="hub-users-table"></tbody>
        </table>
    </div>
</div>

<!-- ===== CHAT TAB ===== -->
<div id="tab-chat" class="tab-content">
    <div class="box">
        <div class="field">
            <label class="label">Hub</label>
            <div class="control"><div class="select is-fullwidth"><select id="chat-hub-select" onchange="loadChatHistory()"></select></div></div>
        </div>
        <div class="chat-log" id="chat-log"></div>
        <div class="field has-addons mt-3">
            <div class="control is-expanded"><input class="input" id="chat-input" placeholder="Type a message..." onkeydown="if(event.key==='Enter')sendChat()"></div>
            <div class="control"><button class="button is-primary" onclick="sendChat()"><span class="icon"><i class="fas fa-paper-plane"></i></span></button></div>
        </div>
    </div>
</div>

<!-- ===== SEARCH TAB ===== -->
<div id="tab-search" class="tab-content">
    <div class="box">
        <h3 class="title is-5">Search</h3>
        <div class="field has-addons">
            <div class="control is-expanded"><input class="input" id="search-input" placeholder="Search files..." onkeydown="if(event.key==='Enter')doSearch()"></div>
            <div class="control">
                <div class="select"><select id="search-type">
                    <option value="0">Any</option><option value="1">Audio</option><option value="2">Compressed</option>
                    <option value="3">Document</option><option value="4">Executable</option><option value="5">Picture</option>
                    <option value="6">Video</option><option value="7">Folder</option><option value="8">TTH</option>
                </select></div>
            </div>
            <div class="control"><button class="button is-primary" onclick="doSearch()"><span class="icon"><i class="fas fa-search"></i></span><span>Search</span></button></div>
        </div>
        <div id="search-status" class="mt-2" style="display:none;"></div>
    </div>
    <div class="box">
        <div class="level">
            <div class="level-left"><h3 class="title is-5">Results <span class="tag is-primary" id="search-count">0</span></h3></div>
            <div class="level-right"><button class="button is-small is-danger is-outlined" onclick="clearSearchResults()"><span class="icon"><i class="fas fa-trash"></i></span><span>Clear</span></button></div>
        </div>
        <div class="table-container">
        <table class="table is-fullwidth is-striped is-hoverable is-narrow">
            <thead><tr><th>File</th><th>Size</th><th>Slots</th><th>TTH</th><th>User</th><th>Actions</th></tr></thead>
            <tbody id="search-results-table"></tbody>
        </table>
        </div>
    </div>
</div>

<!-- ===== QUEUE TAB ===== -->
<div id="tab-queue" class="tab-content">
    <div class="box">
        <div class="level">
            <div class="level-left"><h3 class="title is-5">Download Queue <span class="tag is-primary" id="queue-count">0</span></h3></div>
            <div class="level-right"><button class="button is-small is-danger is-outlined" onclick="clearQueue()"><span class="icon"><i class="fas fa-trash"></i></span><span>Clear All</span></button></div>
        </div>
        <div class="table-container">
        <table class="table is-fullwidth is-striped is-hoverable is-narrow">
            <thead><tr><th>Target</th><th>Size</th><th>Downloaded</th><th>Progress</th><th>Priority</th><th>Actions</th></tr></thead>
            <tbody id="queue-table"></tbody>
        </table>
        </div>
    </div>
</div>

<!-- ===== SHARES TAB ===== -->
<div id="tab-shares" class="tab-content">
    <div class="box">
        <h3 class="title is-5">Add Share</h3>
        <div class="columns">
            <div class="column"><div class="field"><label class="label">Path</label><div class="control"><input class="input" id="share-path" placeholder="/path/to/share"></div></div></div>
            <div class="column is-3"><div class="field"><label class="label">Virtual Name</label><div class="control"><input class="input" id="share-name" placeholder="MyFiles"></div></div></div>
            <div class="column is-2"><div class="field"><label class="label">&nbsp;</label><div class="control"><button class="button is-primary is-fullwidth" onclick="addShare()"><span class="icon"><i class="fas fa-plus"></i></span><span>Add</span></button></div></div></div>
        </div>
    </div>
    <div class="box">
        <div class="level">
            <div class="level-left"><h3 class="title is-5">Shared Directories</h3></div>
            <div class="level-right"><button class="button is-small is-info is-outlined" onclick="refreshShares()"><span class="icon"><i class="fas fa-sync"></i></span><span>Refresh</span></button></div>
        </div>
        <table class="table is-fullwidth is-striped is-hoverable">
            <thead><tr><th>Virtual Name</th><th>Path</th><th>Size</th><th>Actions</th></tr></thead>
            <tbody id="shares-table"></tbody>
        </table>
    </div>
</div>

<!-- ===== SETTINGS TAB ===== -->
<div id="tab-settings" class="tab-content">
    <div class="box">
        <h3 class="title is-5">DC Client Settings</h3>
        <div class="notification is-info is-light">
            <p>Enter a setting name to read or update its value. Common settings: Nick, Description, Connection, DownloadDirectory, Slots, etc.</p>
        </div>
        <div class="columns">
            <div class="column is-5"><div class="field"><label class="label">Setting Name</label><div class="control"><input class="input" id="setting-name" placeholder="Nick"></div></div></div>
            <div class="column is-5"><div class="field"><label class="label">Value</label><div class="control"><input class="input" id="setting-value" placeholder="(value)"></div></div></div>
            <div class="column is-2"><div class="field"><label class="label">&nbsp;</label><div class="control">
                <div class="buttons">
                    <button class="button is-info" onclick="getSetting()"><span class="icon"><i class="fas fa-eye"></i></span></button>
                    <button class="button is-primary" onclick="setSetting()"><span class="icon"><i class="fas fa-save"></i></span></button>
                </div>
            </div></div></div>
        </div>
        <div class="buttons mt-4">
            <button class="button is-warning is-outlined" onclick="reloadConfig()"><span class="icon"><i class="fas fa-redo"></i></span><span>Reload Config</span></button>
            <button class="button is-danger is-outlined" onclick="restartNetworking()"><span class="icon"><i class="fas fa-network-wired"></i></span><span>Restart Networking</span></button>
        </div>
    </div>
</div>

</div><!-- main-content -->

<footer class="footer" style="padding:1rem;">
    <div class="content has-text-centered" style="font-size:0.8rem;">
        <p>eiskaltdcpp-py Dashboard &mdash; <span id="footer-version">v1.0</span></p>
    </div>
</footer>
</div><!-- app-page -->

<script>
// ============================================================================
// State
// ============================================================================
let TOKEN = localStorage.getItem('dc-token') || '';
let USERNAME = localStorage.getItem('dc-user') || '';
let ROLE = localStorage.getItem('dc-role') || '';
let WS = null;
let wsReconnectTimer = null;
const API = '';  // relative to origin
const MAX_EVENTS = 200;
const MAX_CHAT = 500;

// ============================================================================
// Helpers
// ============================================================================
function headers() { return { 'Authorization': `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }; }

async function api(method, path, body) {
    const opts = { method, headers: headers() };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(API + path, opts);
    if (r.status === 401) { doLogout(); throw new Error('Unauthorized'); }
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || e.error || r.statusText); }
    return r.json();
}

function formatBytes(b) {
    if (b === 0) return '0 B';
    const k = 1024, sizes = ['B','KB','MB','GB','TB','PB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return parseFloat((b / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatSpeed(bps) { return formatBytes(bps) + '/s'; }

function formatUptime(sec) {
    sec = Math.floor(sec);
    const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600),
          m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function timeStr() { return new Date().toLocaleTimeString(); }

function escHtml(s) {
    const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}

function notify(msg, type='is-info') {
    const n = document.createElement('div');
    n.className = `notification ${type} is-light fade-in`;
    n.style.cssText = 'position:fixed;top:60px;right:16px;z-index:200;max-width:350px;padding:0.75rem 2.5rem 0.75rem 1rem;';
    n.innerHTML = `<button class="delete" onclick="this.parentElement.remove()"></button>${escHtml(msg)}`;
    document.body.appendChild(n);
    setTimeout(() => n.remove(), 4000);
}

// ============================================================================
// Auth
// ============================================================================
async function doLogin() {
    const user = document.getElementById('login-user').value.trim();
    const pass = document.getElementById('login-pass').value;
    const errEl = document.getElementById('login-error');
    errEl.style.display = 'none';
    try {
        const r = await fetch(API + '/api/auth/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user, password: pass })
        });
        if (!r.ok) { errEl.textContent = 'Invalid username or password'; errEl.style.display = ''; return; }
        const data = await r.json();
        TOKEN = data.access_token;
        USERNAME = user;
        ROLE = data.role;
        localStorage.setItem('dc-token', TOKEN);
        localStorage.setItem('dc-user', USERNAME);
        localStorage.setItem('dc-role', ROLE);
        enterApp();
    } catch (e) { errEl.textContent = 'Connection error'; errEl.style.display = ''; }
}

function doLogout() {
    TOKEN = ''; USERNAME = ''; ROLE = '';
    localStorage.removeItem('dc-token');
    localStorage.removeItem('dc-user');
    localStorage.removeItem('dc-role');
    if (WS) { WS.close(); WS = null; }
    document.getElementById('login-page').style.display = 'flex';
    document.getElementById('app-page').style.display = 'none';
}

async function doShutdown() {
    if (!confirm('Are you sure you want to shut down the server?\\nThis will stop the daemon and API.')) return;
    try {
        await fetch(API + '/api/shutdown', { method: 'POST', headers: headers() });
        document.body.innerHTML = '<div style=\"display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;\"><div style=\"text-align:center;\"><h1>Server shutting down</h1><p>The eispy process has been stopped.</p></div></div>';
    } catch (e) {
        // Connection reset is expected — server is shutting down
        document.body.innerHTML = '<div style=\"display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;\"><div style=\"text-align:center;\"><h1>Server shutting down</h1><p>The eispy process has been stopped.</p></div></div>';
    }
}

function enterApp() {
    document.getElementById('login-page').style.display = 'none';
    document.getElementById('app-page').style.display = 'block';
    document.getElementById('nav-username').textContent = USERNAME;
    initTheme();
    connectWebSocket();
    refreshAll();
}

// Auto-login if token exists
if (TOKEN) {
    // Verify token still works
    fetch(API + '/api/auth/me', { headers: headers() }).then(r => {
        if (r.ok) enterApp(); else doLogout();
    }).catch(() => doLogout());
} else {
    document.getElementById('login-pass').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
}

// ============================================================================
// Theme
// ============================================================================
function initTheme() {
    const t = localStorage.getItem('dc-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', t);
    document.getElementById('theme-icon').className = t === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
}
function toggleTheme() {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('dc-theme', next);
    document.getElementById('theme-icon').className = next === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
}

// ============================================================================
// Tabs
// ============================================================================
function showTab(name) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('is-active'));
    const tab = document.getElementById('tab-' + name);
    if (tab) tab.classList.add('is-active');
    // Refresh data when switching tabs
    if (name === 'hubs') refreshHubs();
    else if (name === 'chat') { refreshHubSelect(); loadChatHistory(); }
    else if (name === 'search') refreshSearchResults();
    else if (name === 'queue') refreshQueue();
    else if (name === 'shares') refreshSharesList();
    else if (name === 'dashboard') refreshAll();
}

// ============================================================================
// WebSocket
// ============================================================================
function connectWebSocket() {
    if (WS && WS.readyState <= 1) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/events?token=${TOKEN}&channels=events,chat,search,transfers,hubs,status`;
    WS = new WebSocket(url);

    WS.onopen = () => {
        document.getElementById('ws-status').className = 'ws-badge connected';
        document.getElementById('ws-status').textContent = 'LIVE';
        if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
    };
    WS.onclose = () => {
        document.getElementById('ws-status').className = 'ws-badge disconnected';
        document.getElementById('ws-status').textContent = 'WS';
        wsReconnectTimer = setTimeout(connectWebSocket, 5000);
    };
    WS.onerror = () => {};
    WS.onmessage = (ev) => {
        try {
            const msg = JSON.parse(ev.data);
            handleWsMessage(msg);
        } catch (e) {}
    };

    // Keepalive
    setInterval(() => { if (WS && WS.readyState === 1) WS.send(JSON.stringify({type:'ping'})); }, 25000);
}

function handleWsMessage(msg) {
    if (msg.type === 'event') {
        addEventLog(msg.event, msg.data);
        handleLiveEvent(msg.event, msg.data);
    } else if (msg.type === 'status') {
        updateStatusCards(msg.data);
    }
}

function addEventLog(event, data) {
    const log = document.getElementById('event-log');
    const entry = document.createElement('div');
    entry.className = 'event-entry';
    let color = '#9cdcfe';
    if (event.includes('chat') || event.includes('message')) color = '#ce9178';
    else if (event.includes('connect')) color = '#89d185';
    else if (event.includes('disconnect') || event.includes('fail')) color = '#f14c4c';
    else if (event.includes('search')) color = '#dcdcaa';
    else if (event.includes('download') || event.includes('upload')) color = '#4ec9b0';
    const summary = Object.values(data).slice(0, 3).join(' | ');
    entry.innerHTML = `<span class="ev-time">${timeStr()}</span><span class="ev-type" style="color:${color}">${event}</span><span style="opacity:0.7">${escHtml(summary)}</span>`;
    log.appendChild(entry);
    while (log.children.length > MAX_EVENTS) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
}

function handleLiveEvent(event, data) {
    // Live chat update
    if ((event === 'chat_message' || event === 'status_message') && document.getElementById('tab-chat').classList.contains('is-active')) {
        const sel = document.getElementById('chat-hub-select');
        if (!sel.value || sel.value === data.hub_url) {
            addChatLine(data);
        }
    }
    // Live search results
    if (event === 'search_result' && document.getElementById('tab-search').classList.contains('is-active')) {
        addSearchResult(data);
    }
    // Queue updates
    if (event.startsWith('queue_') || event.startsWith('download_')) {
        if (document.getElementById('tab-queue').classList.contains('is-active')) refreshQueue();
    }
    // Hub updates
    if (event.startsWith('hub_') || event.startsWith('user_')) {
        if (document.getElementById('tab-dashboard').classList.contains('is-active') ||
            document.getElementById('tab-hubs').classList.contains('is-active')) refreshHubs();
    }
}

// ============================================================================
// Dashboard
// ============================================================================
async function refreshAll() {
    try {
        const [status, transfers] = await Promise.all([
            api('GET', '/api/status'),
            api('GET', '/api/status/transfers').catch(() => null),
        ]);
        document.getElementById('stat-hubs').textContent = status.connected_hubs;
        document.getElementById('stat-share').textContent = formatBytes(status.share_size);
        document.getElementById('stat-queue').textContent = status.queue_size;
        document.getElementById('stat-uptime').textContent = formatUptime(status.uptime_seconds);
        document.getElementById('stat-files').textContent = status.shared_files.toLocaleString();
        document.getElementById('footer-version').textContent = 'v' + status.version;
        if (transfers) {
            document.getElementById('stat-dl-speed').textContent = formatSpeed(transfers.download_speed);
            document.getElementById('stat-ul-speed').textContent = formatSpeed(transfers.upload_speed);
        }
    } catch (e) {}
    refreshHubs();
}

function updateStatusCards(data) {
    if (data.connected_hubs !== undefined) document.getElementById('stat-hubs').textContent = data.connected_hubs;
    if (data.share_size !== undefined) document.getElementById('stat-share').textContent = formatBytes(data.share_size);
    if (data.queue_size !== undefined) document.getElementById('stat-queue').textContent = data.queue_size;
    if (data.shared_files !== undefined) document.getElementById('stat-files').textContent = data.shared_files.toLocaleString();
    if (data.download_speed !== undefined) document.getElementById('stat-dl-speed').textContent = formatSpeed(data.download_speed);
    if (data.upload_speed !== undefined) document.getElementById('stat-ul-speed').textContent = formatSpeed(data.upload_speed);
}

// ============================================================================
// Hubs
// ============================================================================
async function refreshHubs() {
    try {
        const data = await api('GET', '/api/hubs');
        const rows = data.hubs.map(h => `<tr>
            <td><code>${escHtml(h.url)}</code></td>
            <td>${escHtml(h.name)}</td>
            <td>${h.user_count}</td>
            <td><span class="status-dot ${h.connected ? 'online' : 'offline'}"></span>${h.connected ? 'Connected' : 'Offline'}</td>
            <td>
                <button class="button is-small is-info is-outlined" onclick="viewHubUsers('${escHtml(h.url)}')"><span class="icon"><i class="fas fa-users"></i></span></button>
                <button class="button is-small is-danger is-outlined" onclick="disconnectHub('${escHtml(h.url)}')"><span class="icon"><i class="fas fa-times"></i></span></button>
            </td>
        </tr>`).join('');
        document.getElementById('hubs-table').innerHTML = rows || '<tr><td colspan="5" class="has-text-centered" style="opacity:0.5;">No hubs connected</td></tr>';
        // Dashboard mini table (no actions)
        const miniRows = data.hubs.map(h => `<tr>
            <td><code style="font-size:0.8em">${escHtml(h.url)}</code></td>
            <td>${escHtml(h.name)}</td>
            <td>${h.user_count}</td>
            <td><span class="status-dot ${h.connected ? 'online' : 'offline'}"></span></td>
        </tr>`).join('');
        document.getElementById('dash-hubs-table').innerHTML = miniRows || '<tr><td colspan="4" style="opacity:0.5;">No hubs</td></tr>';
        // Update hub selectors
        refreshHubSelect(data.hubs);
    } catch (e) {}
}

async function connectHub() {
    const url = document.getElementById('hub-url-input').value.trim();
    if (!url) return;
    try {
        await api('POST', '/api/hubs/connect', { url });
        document.getElementById('hub-url-input').value = '';
        notify('Connecting to ' + url, 'is-success');
        setTimeout(refreshHubs, 1000);
    } catch (e) { notify(e.message, 'is-danger'); }
}

async function disconnectHub(url) {
    try {
        await api('POST', '/api/hubs/disconnect', { url });
        notify('Disconnected from ' + url);
        refreshHubs();
    } catch (e) { notify(e.message, 'is-danger'); }
}

async function viewHubUsers(url) {
    try {
        const data = await api('GET', '/api/hubs/users?hub_url=' + encodeURIComponent(url));
        document.getElementById('hub-users-title').textContent = url;
        const rows = data.users.map(u => `<tr>
            <td><strong>${escHtml(u.nick)}</strong></td>
            <td>${formatBytes(u.share_size)}</td>
            <td>${escHtml(u.description || '')}</td>
            <td style="opacity:0.6;font-size:0.85em">${escHtml(u.tag || '')}</td>
        </tr>`).join('');
        document.getElementById('hub-users-table').innerHTML = rows || '<tr><td colspan="4" style="opacity:0.5;">No users</td></tr>';
        document.getElementById('hub-users-box').style.display = '';
    } catch (e) { notify(e.message, 'is-danger'); }
}

// ============================================================================
// Chat
// ============================================================================
function refreshHubSelect(hubs) {
    const sel = document.getElementById('chat-hub-select');
    const cur = sel.value;
    if (hubs) {
        sel.innerHTML = '<option value="">All Hubs</option>' + hubs.map(h =>
            `<option value="${escHtml(h.url)}">${escHtml(h.name || h.url)}</option>`
        ).join('');
    }
    if (cur) sel.value = cur;
}

async function loadChatHistory() {
    const hub = document.getElementById('chat-hub-select').value;
    if (!hub) { document.getElementById('chat-log').innerHTML = '<div style="opacity:0.5;">Select a hub to view chat</div>'; return; }
    try {
        const data = await api('GET', '/api/chat/history?hub_url=' + encodeURIComponent(hub) + '&max_lines=200');
        const log = document.getElementById('chat-log');
        log.innerHTML = '';
        for (const line of data.messages) {
            const div = document.createElement('div');
            div.className = 'chat-line';
            div.innerHTML = escHtml(line);
            log.appendChild(div);
        }
        log.scrollTop = log.scrollHeight;
    } catch (e) {}
}

function addChatLine(data) {
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');
    div.className = 'chat-line fade-in';
    const ts = `<span class="timestamp">${timeStr()}</span>`;
    if (data.nick) {
        div.innerHTML = `${ts}<span class="nick">&lt;${escHtml(data.nick)}&gt;</span> ${escHtml(data.message)}`;
    } else {
        div.innerHTML = `${ts}<span style="color:#9cdcfe;">*** ${escHtml(data.message)}</span>`;
    }
    log.appendChild(div);
    while (log.children.length > MAX_CHAT) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
}

async function sendChat() {
    const hub = document.getElementById('chat-hub-select').value;
    const msg = document.getElementById('chat-input').value.trim();
    if (!hub || !msg) return;
    try {
        await api('POST', '/api/chat/message', { hub_url: hub, message: msg });
        document.getElementById('chat-input').value = '';
    } catch (e) { notify(e.message, 'is-danger'); }
}

// ============================================================================
// Search
// ============================================================================
async function doSearch() {
    const q = document.getElementById('search-input').value.trim();
    if (!q) return;
    const ft = parseInt(document.getElementById('search-type').value);
    try {
        await api('POST', '/api/search', { query: q, file_type: ft });
        document.getElementById('search-status').style.display = '';
        document.getElementById('search-status').innerHTML = '<span class="tag is-info is-light"><i class="fas fa-spinner fa-spin mr-2"></i>Searching...</span>';
        document.getElementById('search-results-table').innerHTML = '';
        document.getElementById('search-count').textContent = '0';
        // Results will arrive via WebSocket
    } catch (e) { notify(e.message, 'is-danger'); }
}

function addSearchResult(r) {
    const tbody = document.getElementById('search-results-table');
    const tr = document.createElement('tr');
    tr.className = 'sr-item fade-in';
    const fname = r.file || r.name || '';
    const shortName = fname.split(/[\\/]/).pop();
    tr.innerHTML = `
        <td title="${escHtml(fname)}">${escHtml(shortName)}</td>
        <td>${formatBytes(r.size || 0)}</td>
        <td>${r.free_slots || 0}/${r.total_slots || 0}</td>
        <td style="font-size:0.75em;opacity:0.6;max-width:120px;overflow:hidden;text-overflow:ellipsis;">${escHtml(r.tth || '')}</td>
        <td>${escHtml(r.nick || '')}</td>
        <td><button class="button is-small is-primary is-outlined" onclick="downloadResult(this)" data-tth="${escHtml(r.tth||'')}" data-size="${r.size||0}" data-file="${escHtml(fname)}"><span class="icon"><i class="fas fa-download"></i></span></button></td>
    `;
    tbody.appendChild(tr);
    document.getElementById('search-count').textContent = tbody.children.length;
}

async function refreshSearchResults() {
    try {
        const data = await api('GET', '/api/search/results');
        const tbody = document.getElementById('search-results-table');
        tbody.innerHTML = '';
        for (const r of data.results) addSearchResult(r);
    } catch (e) {}
}

async function clearSearchResults() {
    try {
        await api('DELETE', '/api/search/results');
        document.getElementById('search-results-table').innerHTML = '';
        document.getElementById('search-count').textContent = '0';
        document.getElementById('search-status').style.display = 'none';
    } catch (e) { notify(e.message, 'is-danger'); }
}

async function downloadResult(btn) {
    const tth = btn.dataset.tth;
    const size = parseInt(btn.dataset.size || '0');
    const file = btn.dataset.file;
    const name = file.split(/[\\/]/).pop();
    try {
        await api('POST', '/api/queue', { directory: '', name, size, tth });
        btn.classList.remove('is-outlined');
        btn.innerHTML = '<span class="icon"><i class="fas fa-check"></i></span>';
        notify('Added to queue: ' + name, 'is-success');
    } catch (e) { notify(e.message, 'is-danger'); }
}

// ============================================================================
// Queue
// ============================================================================
async function refreshQueue() {
    try {
        const data = await api('GET', '/api/queue');
        document.getElementById('queue-count').textContent = data.total;
        const rows = data.items.map(q => {
            const pct = q.size > 0 ? Math.round(q.downloaded / q.size * 100) : 0;
            const priLabels = ['Paused','Lowest','Low','Normal','High','Highest'];
            const priColors = ['is-dark','is-light','is-info','is-primary','is-warning','is-danger'];
            const target = q.target.split(/[\\/]/).pop();
            return `<tr>
                <td title="${escHtml(q.target)}">${escHtml(target)}</td>
                <td>${formatBytes(q.size)}</td>
                <td>${formatBytes(q.downloaded)}</td>
                <td><progress class="progress is-small is-primary" value="${pct}" max="100">${pct}%</progress></td>
                <td><span class="tag ${priColors[q.priority] || 'is-light'}">${priLabels[q.priority] || q.priority}</span></td>
                <td><button class="button is-small is-danger is-outlined" onclick="removeFromQueue('${escHtml(q.target).replace(/'/g,"\\'")}')"><span class="icon"><i class="fas fa-times"></i></span></button></td>
            </tr>`;
        }).join('');
        document.getElementById('queue-table').innerHTML = rows || '<tr><td colspan="6" class="has-text-centered" style="opacity:0.5;">Queue is empty</td></tr>';
    } catch (e) {}
}

async function removeFromQueue(target) {
    try { await api('DELETE', '/api/queue/' + encodeURIComponent(target)); refreshQueue(); } catch (e) { notify(e.message, 'is-danger'); }
}

async function clearQueue() {
    if (!confirm('Clear entire download queue?')) return;
    try { await api('DELETE', '/api/queue'); refreshQueue(); } catch (e) { notify(e.message, 'is-danger'); }
}

// ============================================================================
// Shares
// ============================================================================
async function refreshSharesList() {
    try {
        const data = await api('GET', '/api/shares');
        const rows = data.shares.map(s => `<tr>
            <td><strong>${escHtml(s.virtual_name)}</strong></td>
            <td><code style="font-size:0.85em">${escHtml(s.real_path)}</code></td>
            <td>${formatBytes(s.size)}</td>
            <td><button class="button is-small is-danger is-outlined" onclick="removeShare('${escHtml(s.real_path).replace(/'/g,"\\'")}')"><span class="icon"><i class="fas fa-trash"></i></span></button></td>
        </tr>`).join('');
        document.getElementById('shares-table').innerHTML = rows || '<tr><td colspan="4" class="has-text-centered" style="opacity:0.5;">No shares</td></tr>';
    } catch (e) {}
}

async function addShare() {
    const path = document.getElementById('share-path').value.trim();
    const name = document.getElementById('share-name').value.trim();
    if (!path || !name) { notify('Path and virtual name required', 'is-warning'); return; }
    try {
        await api('POST', '/api/shares', { real_path: path, virtual_name: name });
        document.getElementById('share-path').value = '';
        document.getElementById('share-name').value = '';
        notify('Share added', 'is-success');
        refreshSharesList();
    } catch (e) { notify(e.message, 'is-danger'); }
}

async function removeShare(path) {
    try {
        await api('DELETE', '/api/shares?real_path=' + encodeURIComponent(path));
        refreshSharesList();
    } catch (e) { notify(e.message, 'is-danger'); }
}

async function refreshShares() {
    try { await api('POST', '/api/shares/refresh'); notify('Share refresh started', 'is-success'); } catch (e) { notify(e.message, 'is-danger'); }
}

// ============================================================================
// Settings
// ============================================================================
async function getSetting() {
    const name = document.getElementById('setting-name').value.trim();
    if (!name) return;
    try {
        const data = await api('GET', '/api/settings/' + encodeURIComponent(name));
        document.getElementById('setting-value').value = data.value;
    } catch (e) { notify(e.message, 'is-danger'); }
}

async function setSetting() {
    const name = document.getElementById('setting-name').value.trim();
    const value = document.getElementById('setting-value').value;
    if (!name) return;
    try {
        await api('PUT', '/api/settings/' + encodeURIComponent(name), { name, value });
        notify(`Setting '${name}' updated`, 'is-success');
    } catch (e) { notify(e.message, 'is-danger'); }
}

async function reloadConfig() {
    try { await api('POST', '/api/settings/reload'); notify('Config reloaded', 'is-success'); } catch (e) { notify(e.message, 'is-danger'); }
}

async function restartNetworking() {
    try { await api('POST', '/api/settings/networking'); notify('Networking restarted', 'is-success'); } catch (e) { notify(e.message, 'is-danger'); }
}

// ============================================================================
// Auto-refresh
// ============================================================================
setInterval(() => {
    if (document.getElementById('tab-dashboard').classList.contains('is-active')) refreshAll();
}, 30000);
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the web dashboard (SPA — authentication is handled client-side)."""
    return HTMLResponse(content=DASHBOARD_HTML)


@router.get("/dashboard/{path:path}", response_class=HTMLResponse)
async def dashboard_catchall(path: str):
    """Catch-all for SPA client-side routing."""
    return HTMLResponse(content=DASHBOARD_HTML)
