"""
Flask Web Application for Trading Bot Zai v1.2.

Displays TIME-ORDERED signals showing exactly when each trade
should be placed in the user's timezone (UTC+5).

Example display:
  02:40  USDPKR_otc  🔴 DOWN  97.2%  Martingale: 2x
  02:43  USDBRL_otc  🔴 DOWN  96.8%  Martingale: 2x
  02:44  USDJPY      🟢 UP    98.1%  Martingale: 2x
"""

import asyncio
import json
import logging
import threading
import time

from flask import Flask, jsonify, render_template_string, request

from bot.config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG, USER_TZ

logger = logging.getLogger("flask_app")

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Zai v1.2 — Signal Timeline</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0e17;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%);
            border-bottom: 2px solid #21262d;
            padding: 20px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 { font-size: 24px; color: #58a6ff; }
        .header .version { color: #8b949e; font-size: 14px; }
        .status-bar {
            background: #161b22;
            padding: 12px 30px;
            border-bottom: 1px solid #21262d;
            display: flex;
            gap: 30px;
            font-size: 14px;
            flex-wrap: wrap;
        }
        .status-item { display: flex; align-items: center; gap: 8px; }
        .status-dot {
            width: 10px; height: 10px; border-radius: 50%; display: inline-block;
        }
        .status-dot.running { background: #3fb950; animation: pulse 2s infinite; }
        .status-dot.stopped { background: #f85149; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 15px;
            padding: 20px 30px;
        }
        .stat-card {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }
        .stat-card .value { font-size: 28px; font-weight: bold; color: #58a6ff; }
        .stat-card .label { font-size: 12px; color: #8b949e; margin-top: 5px; }
        .timeline-container { padding: 20px 30px; }
        .timeline-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .timeline-header h2 { color: #e0e0e0; font-size: 20px; }
        .filter-btns { display: flex; gap: 10px; }
        .filter-btn {
            padding: 6px 16px;
            border: 1px solid #30363d;
            background: #21262d;
            color: #c9d1d9;
            border-radius: 20px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        .filter-btn.active { background: #58a6ff; color: #fff; border-color: #58a6ff; }
        .filter-btn:hover { background: #30363d; }
        .signals-table {
            width: 100%;
            border-collapse: collapse;
            background: #161b22;
            border-radius: 8px;
            overflow: hidden;
        }
        .signals-table thead th {
            background: #21262d;
            padding: 12px 16px;
            text-align: left;
            font-size: 13px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .signals-table tbody tr {
            border-bottom: 1px solid #21262d;
            transition: background 0.2s;
        }
        .signals-table tbody tr:hover { background: #1c2129; }
        .signals-table tbody td { padding: 12px 16px; font-size: 14px; }
        .time-cell {
            font-family: 'Courier New', monospace;
            font-size: 18px;
            font-weight: bold;
            color: #79c0ff;
        }
        .signal-direction { font-weight: bold; font-size: 16px; }
        .signal-direction.up { color: #3fb950; }
        .signal-direction.down { color: #f85149; }
        .confidence-bar {
            width: 80px; height: 8px; background: #21262d;
            border-radius: 4px; overflow: hidden;
            display: inline-block; vertical-align: middle; margin-right: 8px;
        }
        .confidence-fill { height: 100%; border-radius: 4px; transition: width 0.5s; }
        .confidence-fill.high { background: #3fb950; }
        .confidence-fill.medium { background: #d29922; }
        .confidence-fill.low { background: #f85149; }
        .emoji-icon { font-size: 20px; }
        .category-badge {
            padding: 3px 10px; border-radius: 12px; font-size: 11px; text-transform: uppercase;
        }
        .category-badge.forex { background: #1f3a5f; color: #58a6ff; }
        .category-badge.otc { background: #3f2a1f; color: #d29922; }
        .category-badge.commodity { background: #1f3f2a; color: #3fb950; }
        .category-badge.crypto { background: #3f1f3a; color: #bc8cff; }
        .category-badge.index { background: #2a1f3f; color: #79c0ff; }
        .martingale-badge {
            padding: 2px 8px; border-radius: 8px; font-size: 11px;
            background: #2a1f1f; color: #f0883e;
        }
        .empty-state { text-align: center; padding: 60px 20px; color: #8b949e; }
        .empty-state .icon { font-size: 48px; margin-bottom: 15px; }
        .auto-refresh { color: #8b949e; font-size: 12px; }
        @media (max-width: 768px) {
            .header { flex-direction: column; gap: 10px; }
            .status-bar { flex-wrap: wrap; gap: 15px; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .signals-table { font-size: 12px; }
            .signals-table thead th, .signals-table tbody td { padding: 8px 10px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🤖 Trading Bot Zai v1.2</h1>
            <span class="version">1-Minute Binary Options — Signal Timeline (UTC+5)</span>
        </div>
        <div class="auto-refresh">
            Auto-refresh: <span id="countdown">30</span>s
        </div>
    </div>

    <div class="status-bar">
        <div class="status-item">
            <span class="status-dot" id="statusDot"></span>
            <span id="statusText">Loading...</span>
        </div>
        <div class="status-item">
            Cycle: <strong id="cycleCount">0</strong>
        </div>
        <div class="status-item">
            Assets: <strong id="assetCount">0</strong>
        </div>
        <div class="status-item">
            Local Time: <strong id="localTime">—</strong>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="value" id="totalSignals">0</div>
            <div class="label">Active Signals</div>
        </div>
        <div class="stat-card">
            <div class="value" id="upSignals" style="color: #3fb950">0</div>
            <div class="label">🟢 UP</div>
        </div>
        <div class="stat-card">
            <div class="value" id="downSignals" style="color: #f85149">0</div>
            <div class="label">🔴 DOWN</div>
        </div>
        <div class="stat-card">
            <div class="value" id="avgConfidence" style="color: #d29922">0%</div>
            <div class="label">Avg Confidence</div>
        </div>
        <div class="stat-card">
            <div class="value" id="cacheCount">0</div>
            <div class="label">Cached Assets</div>
        </div>
    </div>

    <div class="timeline-container">
        <div class="timeline-header">
            <h2>📊 Signal Timeline (Next 1 Hour)</h2>
            <div class="filter-btns">
                <button class="filter-btn active" onclick="filterSignals('all')">All</button>
                <button class="filter-btn" onclick="filterSignals('up')">🟢 UP</button>
                <button class="filter-btn" onclick="filterSignals('down')">🔴 DOWN</button>
            </div>
        </div>

        <table class="signals-table" id="signalsTable">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Signal</th>
                    <th>Asset</th>
                    <th>Category</th>
                    <th>Direction</th>
                    <th>Confidence</th>
                    <th>Martingale</th>
                </tr>
            </thead>
            <tbody id="signalsBody">
                <tr>
                    <td colspan="7" class="empty-state">
                        <div class="icon">⏳</div>
                        <div>Waiting for signals...</div>
                        <div style="margin-top:10px;font-size:12px;color:#f0883e;">
                            The bot is analyzing 30 days of historical data for 100+ assets.
                        </div>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>

    <script>
        let currentFilter = 'all';
        let refreshInterval = 30;
        let countdown = refreshInterval;

        function categorize(asset) {
            if (asset.endsWith('_otc')) return 'otc';
            if (asset.startsWith('XAU') || asset.startsWith('XAG')) return 'commodity';
            if (['BTCUSD','ETHUSD','LTCUSD','XRPUSD','ADAUSD'].includes(asset)) return 'crypto';
            if (asset.includes('100') || asset.includes('30') || asset.includes('500') || asset.includes('DAX') || asset.includes('CAC') || asset.includes('NIKKEI')) return 'index';
            return 'forex';
        }

        function filterSignals(filter) {
            currentFilter = filter;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            renderSignals();
        }

        let allSignals = [];

        function renderSignals() {
            const tbody = document.getElementById('signalsBody');
            let filtered = allSignals;
            if (currentFilter === 'up') filtered = allSignals.filter(s => s.direction === 'UP');
            else if (currentFilter === 'down') filtered = allSignals.filter(s => s.direction === 'DOWN');

            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="empty-state"><div class="icon">🔍</div><div>No signals match the filter</div></td></tr>';
                return;
            }

            tbody.innerHTML = filtered.map(s => {
                const cat = categorize(s.asset);
                const confClass = s.confidence >= 95 ? 'high' : s.confidence >= 90 ? 'medium' : 'low';
                const dirClass = s.direction === 'UP' ? 'up' : 'down';
                const emoji = s.direction_emoji || (s.direction === 'UP' ? '🟢' : '🔴');
                const arrow = s.direction_arrow || (s.direction === 'UP' ? '▲' : '▼');
                const martingale = (s.martingale && s.martingale.length > 1)
                    ? `<span class="martingale-badge">${s.martingale[1].amount}x on loss</span>`
                    : '—';
                const tradeTime = s.trade_time_local || '—';

                return `<tr>
                    <td class="time-cell">${tradeTime}</td>
                    <td><span class="emoji-icon">${emoji}</span></td>
                    <td><strong>${s.asset}</strong></td>
                    <td><span class="category-badge ${cat}">${cat}</span></td>
                    <td><span class="signal-direction ${dirClass}">${arrow} ${s.direction}</span></td>
                    <td>
                        <div class="confidence-bar"><div class="confidence-fill ${confClass}" style="width:${s.confidence}%"></div></div>
                        ${s.confidence.toFixed(1)}%
                    </td>
                    <td>${martingale}</td>
                </tr>`;
            }).join('');
        }

        async function refreshData() {
            try {
                const [signalsRes, statusRes] = await Promise.all([
                    fetch('/api/signals'),
                    fetch('/api/status')
                ]);
                const signals = await signalsRes.json();
                const status = await statusRes.json();

                allSignals = signals;

                document.getElementById('totalSignals').textContent = signals.length;
                document.getElementById('upSignals').textContent = signals.filter(s => s.direction === 'UP').length;
                document.getElementById('downSignals').textContent = signals.filter(s => s.direction === 'DOWN').length;

                if (signals.length > 0) {
                    const avg = signals.reduce((sum, s) => sum + s.confidence, 0) / signals.length;
                    document.getElementById('avgConfidence').textContent = avg.toFixed(1) + '%';
                }

                const dot = document.getElementById('statusDot');
                dot.className = 'status-dot ' + (status.running ? 'running' : 'stopped');
                document.getElementById('statusText').textContent = status.status || (status.running ? 'Running' : 'Stopped');
                document.getElementById('cycleCount').textContent = status.cycle_count || 0;
                document.getElementById('assetCount').textContent = (status.assets && status.assets.total_available) || 0;
                document.getElementById('cacheCount').textContent = (status.cache && status.cache.valid_caches) || 0;
                document.getElementById('localTime').textContent = status.local_time || '—';

                renderSignals();
            } catch (e) {
                console.error('Refresh error:', e);
            }
            countdown = refreshInterval;
        }

        setInterval(() => {
            countdown--;
            document.getElementById('countdown').textContent = countdown;
            if (countdown <= 0) refreshData();
        }, 1000);

        refreshData();
    </script>
</body>
</html>
"""


def create_app(scheduler) -> Flask:
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False

    @app.route("/")
    def dashboard():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/signals")
    def api_signals():
        return jsonify(scheduler.current_signals)

    @app.route("/api/status")
    def api_status():
        return jsonify(scheduler.get_status_dict())

    @app.route("/api/history")
    def api_history():
        limit = request.args.get("limit", 100, type=int)
        return jsonify(scheduler.signal_history[-limit:])

    @app.route("/api/assets")
    def api_assets():
        am = scheduler.asset_manager
        return jsonify({"available": am.available_assets, "stats": am.get_stats()})

    @app.route("/api/cache/stats")
    def api_cache_stats():
        return jsonify(scheduler.cache_manager.get_cache_stats())

    return app


def run_flask(scheduler, host: str = FLASK_HOST, port: int = FLASK_PORT):
    app = create_app(scheduler)
    flask_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    flask_thread.start()
    logger.info(f"Flask dashboard running at http://{host}:{port}")
    return flask_thread
