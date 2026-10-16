/* InferForge ERA -- Mission Control Controller
   =============================================== */

const Era = {

    /* ---- Private state ---- */
    _ws: null,
    _clockTimer: null,
    _telemetryTimer: null,
    _uptimeStart: Date.now(),
    _focusedPanel: null,
    _inReplay: false,
    _replayJobWasRunning: false,
    _sessionActive: false,  // true once user runs something in this tab

    /* ============================================================
       INITIALIZATION
       ============================================================ */

    async init() {
        MD.init();

        this._startClock();
        this._startUptime();

        this._loadConfigFromStorage();

        // Check if this tab already had an active session (survives page refresh)
        this._sessionActive = sessionStorage.getItem('inferforge_session_active') === '1';

        if (this._sessionActive) {
            // Returning session — load everything from DB
            await Promise.all([
                this.loadStatus(),
                this.loadFleet(),
                this.loadSessions(),
                this.loadBenchmarks(),
                this.loadDeployments(),
            ]);
        } else {
            // Fresh login — show clean panels (no historical data)
            await this.loadStatus();
            this._showEmptyTelemetry();
            this._showEmptyBenchmarks();
            this._showEmptyDeployments();
        }

        // Always start GPU telemetry polling — so heatmap history
        // accumulates from program start, not just after first message
        this._telemetryTimer = setInterval(() => this._pollTelemetry(), 10000);
        this._pollTelemetry(); // immediate first poll

        this.initKeyboard();
        Chat.initScrollTracking();

        // Wire custom model toggle
        const modelSel = document.getElementById('cfg-model');
        if (modelSel) {
            modelSel.addEventListener('change', () => {
                const row = document.getElementById('cfg-custom-model-row');
                if (row) row.style.display = modelSel.value === 'custom' ? '' : 'none';
            });
        }

        document.getElementById('chat-input')?.focus();
    },


    /* ============================================================
       CLOCK & UPTIME
       ============================================================ */

    _startClock() {
        const update = () => {
            const now = new Date();
            const h = String(now.getHours()).padStart(2, '0');
            const m = String(now.getMinutes()).padStart(2, '0');
            const s = String(now.getSeconds()).padStart(2, '0');
            const el = document.getElementById('era-clock');
            if (el) el.textContent = h + ':' + m + ':' + s;
        };
        update();
        this._clockTimer = setInterval(update, 1000);
    },

    _startUptime() {
        const update = () => {
            const elapsed = Math.floor((Date.now() - this._uptimeStart) / 1000);
            const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
            const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
            const s = String(elapsed % 60).padStart(2, '0');
            const el = document.getElementById('era-uptime');
            if (el) el.textContent = h + ':' + m + ':' + s;
        };
        update();
        setInterval(update, 1000);
    },


    /* ============================================================
       STATUS & API
       ============================================================ */

    async loadStatus() {
        try {
            const s = await API.get('/status');
            State.set('lastApiStatus', s);
            State.set('apiReady', !!s.api_connected);

            const beacon = document.getElementById('era-status-beacon');
            if (beacon) {
                beacon.className = 'era-status-beacon ' + (State.apiReady ? 'online' : 'error');
                beacon.title = State.apiReady ? 'Connected' : (s.api_connection_error || 'Disconnected');
            }
        } catch (e) {
            State.set('apiReady', false);
            const beacon = document.getElementById('era-status-beacon');
            if (beacon) beacon.className = 'era-status-beacon error';
        }
    },


    /* ============================================================
       GPU TELEMETRY
       ============================================================ */

    async loadFleet() {
        try {
            const data = await API.get('/fleet/nodes');
            if (data && data.nodes) {
                this._renderTelemetry(data.nodes);
                const nc = document.getElementById('era-node-count');
                const gc = document.getElementById('era-gpu-count');
                if (nc) nc.textContent = data.nodes.length;
                if (gc) gc.textContent = data.nodes.reduce((s, n) => s + (n.gpu_count || 0), 0);
            }
        } catch (_) {}
    },

    /* Telemetry history — per node aggregates + per-GPU snapshots */
    _telemetryHistory: { labels: [], nodes: {}, gpuSnapshot: {}, gpuHistory: {} },
    _TELEM_MAX_POINTS: 60,
    _telemMetric: 'util',          // heatmap metric: util | temp | power
    _inlineMetric: 'util',         // compact panel metric
    _telemSelectedGpu: null,       // { nodeKey, gpuId } for drill-down
    _telemView: 'heatmap',         // heatmap | timeline

    /** Lightweight poll — always runs, collects GPU history even before session activates */
    async _pollTelemetry() {
        try {
            const liveData = await API.get('/fleet/nodes/telemetry');
            if (!liveData || !liveData.nodes) return;

            const now = new Date();
            const timeLabel = now.getHours().toString().padStart(2,'0') + ':' +
                              now.getMinutes().toString().padStart(2,'0') + ':' +
                              now.getSeconds().toString().padStart(2,'0');
            const h = this._telemetryHistory;
            h.labels.push(timeLabel);
            if (h.labels.length > this._TELEM_MAX_POINTS) h.labels.shift();

            for (const node of liveData.nodes) {
                const gpus = node.gpus || [];
                if (!gpus.length) continue;
                const nodeKey = node.ip || node.hostname;
                if (!h.nodes[nodeKey]) h.nodes[nodeKey] = { ip: nodeKey, util: [], temp: [], power: [] };
                const nd = h.nodes[nodeKey];
                nd.util.push(node.avg_util || 0);
                nd.temp.push(node.avg_temp || 0);
                nd.power.push(node.total_power || 0);
                if (nd.util.length > this._TELEM_MAX_POINTS) { nd.util.shift(); nd.temp.shift(); nd.power.shift(); }

                h.gpuSnapshot[nodeKey] = gpus;
                for (const g of gpus) {
                    const gKey = nodeKey + ':' + g.gpu_id;
                    if (!h.gpuHistory[gKey]) h.gpuHistory[gKey] = { util: [], temp: [], power: [] };
                    const gh = h.gpuHistory[gKey];
                    gh.util.push(g.utilization || 0);
                    gh.temp.push(g.temperature || 0);
                    gh.power.push(g.power || 0);
                    if (gh.util.length > this._TELEM_MAX_POINTS) { gh.util.shift(); gh.temp.shift(); gh.power.shift(); }
                }
            }

            // If session active, update the full telemetry UI
            if (this._sessionActive) {
                await this.refreshTelemetry();
            } else {
                // Just refresh the inline heatmap and modal drill-down if open
                this._renderInlineHeatmap();
                const modal = document.getElementById('telem-modal');
                if (modal && modal.classList.contains('open')) {
                    // Only refresh the drill-down, not the whole heatmap (avoids flicker)
                    if (this._telemSelectedGpu) {
                        this._renderDrilldown(this._telemSelectedGpu.nodeKey, this._telemSelectedGpu.gpuId);
                    }
                }
            }
        } catch (_) {}
    },

    async refreshTelemetry() {
        try {
            // Fetch fleet node info (for card rendering)
            const fleetData = await API.get('/fleet/nodes');

            // Fetch live GPU stats via SSH
            let liveData = null;
            try {
                liveData = await API.get('/fleet/nodes/telemetry');
            } catch (_) {}

            if (fleetData && fleetData.nodes) {
                // Merge live data into fleet nodes
                if (liveData && liveData.nodes) {
                    for (const live of liveData.nodes) {
                        const fleet = fleetData.nodes.find(n =>
                            n.ip === live.ip || n.hostname === live.hostname ||
                            n.ip_address === live.ip
                        );
                        if (fleet && live.gpus && live.gpus.length > 0) {
                            fleet.gpus = live.gpus;
                        }
                    }
                }

                this._renderTelemetry(fleetData.nodes);
                const nc = document.getElementById('era-node-count');
                const gc = document.getElementById('era-gpu-count');
                if (nc) nc.textContent = fleetData.nodes.length;
                if (gc) gc.textContent = fleetData.nodes.reduce((s, n) => s + (n.gpu_count || 0), 0);
                const badge = document.getElementById('telemetry-status');
                if (badge) badge.textContent = 'LIVE';
            }

            // Update telemetry history — per-node + per-GPU
            if (liveData && liveData.nodes) {
                const now = new Date();
                const timeLabel = now.getHours().toString().padStart(2, '0') + ':' +
                                 now.getMinutes().toString().padStart(2, '0') + ':' +
                                 now.getSeconds().toString().padStart(2, '0');

                const h = this._telemetryHistory;
                h.labels.push(timeLabel);
                if (h.labels.length > this._TELEM_MAX_POINTS) h.labels.shift();

                for (const node of liveData.nodes) {
                    const gpus = node.gpus || [];
                    if (gpus.length === 0) continue;
                    const nodeKey = node.ip || node.hostname;

                    // Per-node time-series
                    if (!h.nodes[nodeKey]) h.nodes[nodeKey] = { ip: nodeKey, util: [], temp: [], power: [] };
                    const nd = h.nodes[nodeKey];
                    nd.util.push(node.avg_util || 0);
                    nd.temp.push(node.avg_temp || 0);
                    nd.power.push(node.total_power || 0);
                    if (nd.util.length > this._TELEM_MAX_POINTS) { nd.util.shift(); nd.temp.shift(); nd.power.shift(); }

                    // Per-GPU snapshot (latest values for heatmap)
                    h.gpuSnapshot[nodeKey] = gpus;

                    // Per-GPU time-series (for drill-down charts)
                    for (const g of gpus) {
                        const gKey = nodeKey + ':' + g.gpu_id;
                        if (!h.gpuHistory[gKey]) h.gpuHistory[gKey] = { util: [], temp: [], power: [] };
                        const gh = h.gpuHistory[gKey];
                        gh.util.push(g.utilization || 0);
                        gh.temp.push(g.temperature || 0);
                        gh.power.push(g.power || 0);
                        if (gh.util.length > this._TELEM_MAX_POINTS) { gh.util.shift(); gh.temp.shift(); gh.power.shift(); }
                    }
                }

                if (Object.keys(h.nodes).length > 0) {
                    this._renderTelemetryChart();
                    this._renderInlineHeatmap();
                    // Refresh modal if open — only redraw drill-down charts (no flicker)
                    const modal = document.getElementById('telem-modal');
                    if (modal && modal.classList.contains('open')) {
                        if (this._telemSelectedGpu) {
                            this._renderDrilldown(
                                this._telemSelectedGpu.nodeKey,
                                this._telemSelectedGpu.gpuId
                            );
                        } else {
                            this._renderTelemModal();
                        }
                    }
                }
            }
        } catch (_) {
            const badge = document.getElementById('telemetry-status');
            if (badge) badge.textContent = 'OFFLINE';
        }
    },

    _renderTelemetryChart() {
        const canvas = document.getElementById('canvas-telemetry');
        if (!canvas) return;
        const h = this._telemetryHistory;
        if (!h.labels.length) return;

        const NODE_PALETTES = [
            { util: '#00d4ff', temp: '#ffaa00', power: '#00c896' },
            { util: '#cc66ff', temp: '#ff5555', power: '#44eebb' },
            { util: '#4488ff', temp: '#ff8844', power: '#88ff44' },
            { util: '#ff4466', temp: '#ffcc00', power: '#00aaff' },
        ];

        const nodeKeys = Object.keys(h.nodes);

        // --- Compact view: one UTIL line per node (clean, no overlap) ---
        const compactSeries = nodeKeys.map((key, i) => {
            const nd = h.nodes[key];
            const pal = NODE_PALETTES[i % NODE_PALETTES.length];
            const lastVal = nd.util[nd.util.length - 1] || 0;
            return {
                name: '.' + key.split('.').pop(),
                color: pal.util,
                unit: '%',
                data: nd.util,
                _lastUtil: lastVal,
                _lastTemp: nd.temp[nd.temp.length - 1] || 0,
                _lastPwr:  nd.power[nd.power.length - 1] || 0,
                _pal: pal,
                _key: key,
            };
        });

        const h_px = canvas.parentElement?.clientHeight || 120;
        Charts.drawMultiLineChart(canvas, compactSeries, h.labels, {
            title: '',
            height: h_px,
            hideLegend: true,
        });

        // Compact legend: node IP + current UTIL/TEMP/PWR inline
        const legendEl = document.getElementById('telem-legend');
        if (legendEl) {
            legendEl.innerHTML = compactSeries.map(s =>
                '<span class="era-telem-legend-item">' +
                '<span class="era-telem-legend-swatch" style="background:' + s.color + '"></span>' +
                '<span style="color:#aab">' + s._key + '</span> ' +
                'UTIL:<span class="era-telem-legend-val" style="color:' + s._pal.util + '">' + s._lastUtil + '%</span> ' +
                'TEMP:<span class="era-telem-legend-val" style="color:' + s._pal.temp + '">' + s._lastTemp + 'C</span> ' +
                'PWR:<span class="era-telem-legend-val" style="color:' + s._pal.power + '">' + s._lastPwr + 'W</span>' +
                '</span>'
            ).join('');
        }

        // If modal is open, refresh it too
        const modal = document.getElementById('telem-modal');
        if (modal && modal.classList.contains('open')) {
            this._renderTelemModal();
        }
    },

    _renderTelemModal() {
        const h = this._telemetryHistory;
        const container = document.getElementById('telem-modal-charts');
        if (!container) return;

        if (this._telemView === 'heatmap') {
            this._renderHeatmap(container, h);
        } else {
            this._renderTimeline(container, h);
        }
    },

    /* ---- Heatmap view (node × GPU grid) ---- */
    _renderHeatmap(container, h) {
        const nodeKeys = Object.keys(h.gpuSnapshot);
        if (!nodeKeys.length) {
            container.innerHTML = '<div style="padding:20px;color:var(--text-dim);font-family:var(--mono)">No GPU data yet — telemetry refreshes every 10s.</div>';
            return;
        }

        const metric = this._telemMetric;
        const maxGpus = Math.max(...nodeKeys.map(k => (h.gpuSnapshot[k] || []).length));

        // Color scale function
        const _color = (val, metric) => {
            if (metric === 'util') {
                if (val >= 90) return { bg: '#5f0000', fg: '#ff4466', bdr: '#ff2244' };
                if (val >= 70) return { bg: '#4a3000', fg: '#ffaa00', bdr: '#ffaa00' };
                if (val >= 30) return { bg: '#003a25', fg: '#00c896', bdr: '#00c896' };
                if (val >= 5)  return { bg: '#001a12', fg: '#00885a', bdr: '#00663d' };
                return { bg: '#0d0d14', fg: '#444466', bdr: '#222233' };
            }
            if (metric === 'temp') {
                if (val >= 90) return { bg: '#5f0000', fg: '#ff4466', bdr: '#ff2244' };
                if (val >= 75) return { bg: '#4a2000', fg: '#ff7700', bdr: '#ff5500' };
                if (val >= 55) return { bg: '#3a2800', fg: '#ffaa00', bdr: '#ffaa00' };
                if (val >= 35) return { bg: '#001a12', fg: '#00c896', bdr: '#00c896' };
                return { bg: '#000d1a', fg: '#0088cc', bdr: '#004488' };
            }
            // power (normalize to 200W/GPU as 100%)
            const pct = Math.min(val / 200 * 100, 100);
            if (pct >= 85) return { bg: '#5f0000', fg: '#ff4466', bdr: '#ff2244' };
            if (pct >= 60) return { bg: '#4a3000', fg: '#ffaa00', bdr: '#ffaa00' };
            if (pct >= 30) return { bg: '#003a25', fg: '#00c896', bdr: '#00c896' };
            return { bg: '#0d0d14', fg: '#444466', bdr: '#222233' };
        };

        const sel = this._telemSelectedGpu;

        // Build header row
        let gpuHeaders = '';
        for (let g = 0; g < maxGpus; g++) {
            gpuHeaders += '<th>GPU&nbsp;' + g + '</th>';
        }

        // Build node rows
        let rows = '';
        for (const nodeKey of nodeKeys) {
            const gpus = h.gpuSnapshot[nodeKey] || [];
            const nd = h.nodes[nodeKey] || {};
            const lastUtil  = (nd.util  || [0]).slice(-1)[0] || 0;
            const lastTemp  = (nd.temp  || [0]).slice(-1)[0] || 0;
            const lastPwr   = (nd.power || [0]).slice(-1)[0] || 0;
            const shortIp = nodeKey.split('.').slice(-2).join('.');

            let cells = '';
            for (let g = 0; g < maxGpus; g++) {
                const gpu = gpus[g];
                if (!gpu) { cells += '<td class="era-hm-cell era-hm-nodata">—</td>'; continue; }
                let val = metric === 'util' ? gpu.utilization : metric === 'temp' ? gpu.temperature : gpu.power;
                val = val || 0;
                const c = _color(val, metric);
                const isSelected = sel && sel.nodeKey === nodeKey && sel.gpuId === g;
                const unit = metric === 'util' ? '%' : metric === 'temp' ? '°' : 'W';
                cells += '<td class="era-hm-cell' + (isSelected ? ' selected' : '') + '"' +
                    ' style="background:' + c.bg + ';color:' + c.fg + ';border-color:' + c.bdr + '"' +
                    ' onclick="Era._selectGpu(\'' + nodeKey + '\',' + g + ')"' +
                    ' title="' + nodeKey + ' GPU' + g + ': ' + val + unit + '">' +
                    val + '</td>';
            }

            rows += '<tr>' +
                '<td class="era-hm-node" title="' + nodeKey + '">' + shortIp + '</td>' +
                cells +
                '<td class="era-hm-summary">' +
                '<span style="color:#00d4ff">' + lastUtil + '%</span> ' +
                '<span style="color:#ffaa00">' + lastTemp + 'C</span> ' +
                '<span style="color:#00c896">' + lastPwr + 'W</span>' +
                '</td></tr>';
        }

        // Legend bar
        const unit = metric === 'util' ? '%' : metric === 'temp' ? '°C' : 'W';
        const legendRange = metric === 'util' ? '0 → 100' : metric === 'temp' ? '0 → 100' : '0 → 200';

        container.innerHTML =
            '<div class="era-hm-wrap">' +
              '<div class="era-hm-left">' +
                '<table class="era-hm-table">' +
                  '<thead><tr><th>Node</th>' + gpuHeaders + '<th>Avg</th></tr></thead>' +
                  '<tbody>' + rows + '</tbody>' +
                '</table>' +
                '<div class="era-hm-legend-bar">' +
                  '<span style="font-size:9px;font-family:var(--mono);color:var(--text-dim)">' + legendRange + unit + '</span>' +
                  '<div class="era-hm-gradient" style="background:linear-gradient(to right,' +
                    (metric === 'util' ? '#0d0d14,#003a25,#00c896,#ffaa00,#ff4466' :
                     metric === 'temp' ? '#000d1a,#003a25,#ffaa00,#ff4466' :
                     '#0d0d14,#003a25,#00c896,#ffaa00,#ff4466') + ')"></div>' +
                  '<div class="era-hm-legend-labels"><span>Low</span><span>High</span></div>' +
                '</div>' +
              '</div>' +
              '<div class="era-hm-right" id="hm-drilldown">' +
                (sel ? '' : '<div class="era-hm-hint">Click any GPU cell<br>for drill-down</div>') +
              '</div>' +
            '</div>';

        if (sel) this._renderDrilldown(sel.nodeKey, sel.gpuId);
    },

    _selectGpu(nodeKey, gpuId) {
        this._telemSelectedGpu = { nodeKey, gpuId };
        // Re-render heatmap to highlight selected + show drill-down
        const h = this._telemetryHistory;
        const container = document.getElementById('telem-modal-charts');
        if (container) this._renderHeatmap(container, h);
    },

    _renderDrilldown(nodeKey, gpuId) {
        const h = this._telemetryHistory;
        const panel = document.getElementById('hm-drilldown');
        if (!panel) return;

        const gKey = nodeKey + ':' + gpuId;
        const gh = h.gpuHistory[gKey];
        const snap = (h.gpuSnapshot[nodeKey] || [])[gpuId];
        if (!snap) { panel.innerHTML = '<div class="era-hm-hint">No data for this GPU yet.<br>Telemetry refreshes every 10s.</div>'; return; }

        const util  = snap.utilization || 0;
        const temp  = snap.temperature || 0;
        const power = snap.power || 0;
        const lastLabel = h.labels[h.labels.length - 1] || '--';

        const hasHistory = gh && h.labels.length >= 2;

        panel.innerHTML =
            '<div class="era-dd-header">' +
              '<div class="era-dd-title">' + nodeKey + ' / GPU ' + gpuId + '</div>' +
              '<div class="era-dd-sub">AMD Instinct MI300X</div>' +
            '</div>' +

            '<div class="era-dd-section">' +
              '<div class="era-dd-section-header">' +
                '<span class="era-dd-section-label">Utilization</span>' +
                '<span class="era-dd-section-val" style="color:#00d4ff">' + util + '%</span>' +
              '</div>' +
              '<canvas id="dd-canvas-util" class="era-dd-canvas"></canvas>' +
            '</div>' +

            '<div class="era-dd-section">' +
              '<div class="era-dd-section-header">' +
                '<span class="era-dd-section-label">Hotspot Temperature</span>' +
                '<span class="era-dd-section-val" style="color:#ffaa00">' + temp + '°C</span>' +
              '</div>' +
              '<canvas id="dd-canvas-temp" class="era-dd-canvas"></canvas>' +
            '</div>' +

            '<div class="era-dd-section">' +
              '<div class="era-dd-section-header">' +
                '<span class="era-dd-section-label">Power</span>' +
                '<span class="era-dd-section-val" style="color:#00c896">' + power + 'W</span>' +
              '</div>' +
              '<canvas id="dd-canvas-pwr" class="era-dd-canvas"></canvas>' +
            '</div>' +

            '<div class="era-dd-footer">' +
              '<span>Last sample: ' + lastLabel + '</span>' +
              '<span>' + h.labels.length + ' points</span>' +
            '</div>';

        if (hasHistory) {
            const opts = { height: 110, hideLegend: true };
            Charts.drawMultiLineChart(document.getElementById('dd-canvas-util'),
                [{ name: 'Utilization', color: '#00d4ff', unit: '%', data: gh.util }], h.labels, opts);
            Charts.drawMultiLineChart(document.getElementById('dd-canvas-temp'),
                [{ name: 'Temperature', color: '#ffaa00', unit: 'C', data: gh.temp }], h.labels, opts);
            Charts.drawMultiLineChart(document.getElementById('dd-canvas-pwr'),
                [{ name: 'Power', color: '#00c896', unit: 'W', data: gh.power }], h.labels, opts);
        }
    },

    /* ---- Timeline view (per-node charts) ---- */
    _renderTimeline(container, h) {
        const nodeKeys = Object.keys(h.nodes);
        if (!nodeKeys.length || h.labels.length < 2) {
            container.innerHTML = '<div style="padding:20px;color:var(--text-dim);font-family:var(--mono)">No timeline data yet.</div>';
            return;
        }
        const NODE_PALETTES = [
            { util: '#00d4ff', temp: '#ffaa00', power: '#00c896' },
            { util: '#cc66ff', temp: '#ff5555', power: '#44eebb' },
            { util: '#4488ff', temp: '#ff8844', power: '#88ff44' },
        ];
        container.innerHTML = '';
        nodeKeys.forEach((key, i) => {
            const nd = h.nodes[key];
            const pal = NODE_PALETTES[i % NODE_PALETTES.length];
            const lastUtil  = (nd.util || [0]).slice(-1)[0] || 0;
            const lastTemp  = (nd.temp || [0]).slice(-1)[0] || 0;
            const lastPwr   = (nd.power || [0]).slice(-1)[0] || 0;
            const card = document.createElement('div');
            card.className = 'era-node-chart-card';
            card.innerHTML =
                '<div class="era-node-chart-title">' +
                '<span style="color:' + pal.util + '">' + key + '</span>' +
                '<span class="badge">MI300X · 8 GPUs</span>' +
                '</div>' +
                '<div class="era-node-chart-stats">' +
                '<span><span class="stat-k">UTIL</span><span class="stat-v" style="color:' + pal.util + '">' + lastUtil + '%</span></span>' +
                '<span><span class="stat-k">TEMP</span><span class="stat-v" style="color:' + pal.temp + '">' + lastTemp + 'C</span></span>' +
                '<span><span class="stat-k">PWR</span><span class="stat-v" style="color:' + pal.power + '">' + lastPwr + 'W</span></span>' +
                '</div>' +
                '<canvas id="telem-canvas-' + i + '"></canvas>';
            container.appendChild(card);
            const canvas = document.getElementById('telem-canvas-' + i);
            if (canvas) {
                Charts.drawMultiLineChart(canvas, [
                    { name: 'UTIL', color: pal.util,  unit: '%', data: nd.util  },
                    { name: 'TEMP', color: pal.temp,  unit: 'C', data: nd.temp  },
                    { name: 'PWR',  color: pal.power, unit: 'W', data: nd.power },
                ], h.labels, { title: '', height: 180, hideLegend: false });
            }
        });
    },

    /* Inline heatmap (compact, inside main telemetry panel) */
    setInlineMetric(metric) {
        this._inlineMetric = metric;
        ['util','temp','power'].forEach(m => {
            const btn = document.getElementById('inline-metric-' + m);
            if (btn) btn.classList.toggle('active', m === metric);
        });
        this._renderInlineHeatmap();
    },

    _renderInlineHeatmap() {
        const h = this._telemetryHistory;
        const el = document.getElementById('inline-heatmap');
        if (!el) return;

        const nodeKeys = Object.keys(h.gpuSnapshot);
        if (!nodeKeys.length) {
            el.innerHTML = '<div style="font-family:var(--mono);font-size:9px;color:var(--text-dim);padding:4px 0">No live GPU data — click Detect GPUs</div>';
            return;
        }

        const metric = this._inlineMetric;
        const maxGpus = Math.max(...nodeKeys.map(k => (h.gpuSnapshot[k] || []).length));

        const _color = (val, metric) => {
            if (metric === 'util') {
                if (val >= 90) return { bg: '#5f0000', fg: '#ff4466' };
                if (val >= 70) return { bg: '#4a3000', fg: '#ffaa00' };
                if (val >= 30) return { bg: '#003a25', fg: '#00c896' };
                if (val >= 5)  return { bg: '#001a12', fg: '#00885a' };
                return { bg: '#0d0d14', fg: '#333355' };
            }
            if (metric === 'temp') {
                if (val >= 90) return { bg: '#5f0000', fg: '#ff4466' };
                if (val >= 75) return { bg: '#4a2000', fg: '#ff7700' };
                if (val >= 55) return { bg: '#3a2800', fg: '#ffaa00' };
                if (val >= 35) return { bg: '#001a12', fg: '#00c896' };
                return { bg: '#000d1a', fg: '#0088cc' };
            }
            const pct = Math.min(val / 200 * 100, 100);
            if (pct >= 85) return { bg: '#5f0000', fg: '#ff4466' };
            if (pct >= 60) return { bg: '#4a3000', fg: '#ffaa00' };
            if (pct >= 30) return { bg: '#003a25', fg: '#00c896' };
            return { bg: '#0d0d14', fg: '#333355' };
        };

        const unit = metric === 'util' ? '%' : metric === 'temp' ? '°' : 'W';

        let html = '<table class="era-inline-hm-table">';
        // Header
        html += '<tr><th></th>';
        for (let g = 0; g < maxGpus; g++) html += '<th>G' + g + '</th>';
        html += '</tr>';

        for (const nodeKey of nodeKeys) {
            const gpus = h.gpuSnapshot[nodeKey] || [];
            const shortIp = nodeKey.split('.').slice(-2).join('.');
            html += '<tr><td class="era-inline-hm-node">' + shortIp + '</td>';
            for (let g = 0; g < maxGpus; g++) {
                const gpu = gpus[g];
                if (!gpu) { html += '<td class="era-inline-hm-cell" style="color:#333">—</td>'; continue; }
                const val = metric === 'util' ? (gpu.utilization || 0) : metric === 'temp' ? (gpu.temperature || 0) : (gpu.power || 0);
                const c = _color(val, metric);
                html += '<td class="era-inline-hm-cell" style="background:' + c.bg + ';color:' + c.fg + '"' +
                    ' onclick="Era.openTelemModal()" title="' + nodeKey + ' GPU' + g + ': ' + val + unit + '">' +
                    val + '</td>';
            }
            html += '</tr>';
        }
        html += '</table>';
        el.innerHTML = html;
    },

    setTelemView(view) {
        this._telemView = view;
        document.querySelectorAll('.era-telem-tab').forEach(b => b.classList.remove('active'));
        const btn = document.getElementById('telem-tab-' + view);
        if (btn) btn.classList.add('active');
        this._renderTelemModal();
    },

    setTelemMetric(metric) {
        this._telemMetric = metric;
        document.querySelectorAll('.era-metric-btn').forEach(b => b.classList.remove('active'));
        const btn = document.getElementById('metric-btn-' + metric);
        if (btn) btn.classList.add('active');
        if (this._telemView === 'heatmap') {
            const h = this._telemetryHistory;
            const container = document.getElementById('telem-modal-charts');
            if (container) this._renderHeatmap(container, h);
        }
    },

    openTelemModal() {
        const modal = document.getElementById('telem-modal');
        if (!modal) return;
        modal.classList.add('open');
        this._renderTelemModal();
    },

    closeTelemModal(e) {
        const modal = document.getElementById('telem-modal');
        if (modal) modal.classList.remove('open');
    },

    _renderTelemetry(nodes) {
        const grid = document.getElementById('telemetry-grid');
        if (!grid) return;
        grid.innerHTML = '';

        if (!nodes || !nodes.length) {
            grid.innerHTML = '<div class="era-empty-panel"><div class="era-empty-label">AWAITING NODE DATA</div><div class="era-empty-hint">Configure cluster and run GPU detection</div></div>';
            return;
        }

        for (const node of nodes) {
            const card = document.createElement('div');
            card.className = 'era-node-card';

            const isOnline = node.status === 'online';
            const isBusy = node.status === 'busy';
            const statusClass = isOnline ? 'online' : isBusy ? 'busy' : node.status === 'unknown' ? 'unknown' : 'offline';
            const gpuCount = (node.gpu_count != null && node.gpu_count > 0) ? node.gpu_count : (node.gpus?.length || 0);
            const gpuModel = node.gpu_model || node.gpu_platform || node.platform || '';
            const hbm = node.hbm_per_gpu || node.hbm_per_gpu_gb || 0;
            const totalHbm = hbm * gpuCount;
            const gpus = node.gpus || [];
            const hasLiveData = gpus.length > 0 && gpus.some(g => g.utilization > 0 || g.temperature > 0 || g.power > 0);

            // Compact GPU chips: ✓ for each GPU, or utilization % if live data
            let gpuChipsHTML = '';
            if (gpuCount > 0 && !hasLiveData) {
                // No live data — show checkmark chips
                const checks = [];
                for (let i = 0; i < gpuCount; i++) {
                    checks.push('<span class="era-gpu-chip ' + (isOnline ? 'online' : 'idle') +
                        '" title="GPU' + i + '">' + (isOnline ? '✓' : '·') + '</span>');
                }
                gpuChipsHTML = '<div class="era-gpu-chips">' + checks.join('') +
                    '<span class="era-gpu-chip-label">' + gpuCount + '/' + gpuCount +
                    (isOnline ? ' online' : ' idle') + '</span></div>';
            } else if (hasLiveData) {
                // Live utilization data — unique color per GPU, always visible
                const _GPU_COLORS = [
                    '#00d4ff', '#00c896', '#ffaa00', '#8866ff',
                    '#ff4466', '#4488ff', '#ff8844', '#44ffcc',
                ];
                let barsHTML = '';
                for (let i = 0; i < Math.min(gpus.length, 8); i++) {
                    const g = gpus[i];
                    const util = g.utilization || 0;
                    const color = _GPU_COLORS[i % _GPU_COLORS.length];
                    // Always show colored bar (min-height 5px from CSS), height scales with util
                    barsHTML += '<div class="era-gpu-mini" title="GPU' + i + ': ' + util + '% · ' +
                        (g.temperature || '--') + '°C · ' + (g.power || '--') + 'W">' +
                        '<span class="era-mini-fill" style="height:' + util + '%;background:' + color + '80;border-top:2px solid ' + color + '"></span>' +
                        '</div>';
                }
                gpuChipsHTML = '<div class="era-gpu-mini-row">' + barsHTML + '</div>';
            }

            // Stats row: avg util, temp, power (if live data)
            let statsHTML = '';
            if (hasLiveData) {
                const avgUtil = Math.round(gpus.reduce((s, g) => s + (g.utilization || 0), 0) / gpus.length);
                const avgTemp = Math.round(gpus.reduce((s, g) => s + (g.temperature || 0), 0) / gpus.length);
                const totalPower = Math.round(gpus.reduce((s, g) => s + (g.power || 0), 0));
                statsHTML = '<div class="era-node-stats">' +
                    '<span class="era-stat"><span class="era-stat-k">UTIL</span><span class="era-stat-v">' + avgUtil + '%</span></span>' +
                    '<span class="era-stat"><span class="era-stat-k">TEMP</span><span class="era-stat-v">' + avgTemp + '°C</span></span>' +
                    '<span class="era-stat"><span class="era-stat-k">PWR</span><span class="era-stat-v">' + totalPower + 'W</span></span>' +
                    '</div>';
            } else if (gpuCount > 0) {
                statsHTML = '<div class="era-node-stats">' +
                    '<span class="era-stat"><span class="era-stat-k">UTIL</span><span class="era-stat-v dim">--</span></span>' +
                    '<span class="era-stat"><span class="era-stat-k">TEMP</span><span class="era-stat-v dim">--</span></span>' +
                    '<span class="era-stat"><span class="era-stat-k">PWR</span><span class="era-stat-v dim">--</span></span>' +
                    '</div>';
            }

            // Spec line: MI300X · 8 GPUs · 192 GB · 1,536 GB total
            let specHTML = '';
            if (gpuModel || gpuCount > 0) {
                const parts = [];
                if (gpuModel) parts.push('<strong>' + _esc(gpuModel) + '</strong>');
                if (gpuCount > 0) parts.push(gpuCount + ' GPUs');
                if (hbm > 0) parts.push(hbm + ' GB/GPU');
                if (totalHbm > 0) parts.push(totalHbm.toLocaleString() + ' GB total');
                specHTML = '<div class="era-node-spec">' + parts.join(' · ') + '</div>';
            } else {
                specHTML = '<div class="era-node-spec dim">No GPU data — run Detect GPUs</div>';
            }

            card.innerHTML =
                '<div class="era-node-header">' +
                '  <span class="era-node-name">' + _esc(node.ip || node.hostname || 'Unknown') + '</span>' +
                '  <span class="era-node-status ' + statusClass + '">' + statusClass.toUpperCase() + '</span>' +
                '</div>' +
                specHTML +
                gpuChipsHTML +
                statsHTML;

            grid.appendChild(card);
        }
    },

    _updateHeaderStats(state) {
        // Never overwrite gpu-count here — loadFleet() sets the fleet-wide total.
        // Only update the session indicator with the GPU model.
        if (state.gpu_model) {
            const si = document.getElementById('era-session-indicator');
            if (si) {
                si.classList.add('active');
                const label = document.getElementById('era-session-label');
                if (label) label.textContent = state.gpu_model;
            }
        }
    },


    /* ============================================================
       OPTIMIZATION TIMELINE
       ============================================================ */

    async loadSessions() {
        try {
            const data = await API.get('/hyperloom/sessions');
            if (!data || !data.sessions) return;

            const sel = document.getElementById('timeline-session-select');
            if (!sel) return;
            sel.innerHTML = '<option value="">Select Session</option>';

            for (const s of data.sessions) {
                const opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = (s.model || 'Session') + ' - ' + (s.status || 'unknown');
                sel.appendChild(opt);
            }

            if (data.sessions.length > 0) {
                sel.value = data.sessions[0].id;
                this.loadTimeline();
            }
        } catch (_) {}
    },

    async loadTimeline() {
        const sel = document.getElementById('timeline-session-select');
        const sessionId = sel ? sel.value : '';
        if (!sessionId) return;

        try {
            const data = await API.get('/hyperloom/sessions/' + sessionId + '/timeline');
            if (!data || !data.phases) return;

            const phaseBadge = document.getElementById('timeline-phase');
            const currentPhase = data.current_phase || data.phases[data.phases.length - 1]?.name || '--';
            if (phaseBadge) phaseBadge.textContent = currentPhase.toUpperCase();

            const phaseColors = {
                'PRELUDE':          '#4488ff',
                'ENABLEMENT':       '#ffaa00',
                'FRAMEWORK_AGENT':  '#00c896',
                'KERNEL_AGENT':     '#8866ff',
                'SWEEP':            '#00d4ff',
                'CLOSE':            '#666680',
            };

            const events = data.phases.map(p => ({
                label: p.name || p.phase || '',
                start: p.start_time || 0,
                end: p.end_time || p.start_time + (p.duration || 60),
                color: phaseColors[p.name] || phaseColors[p.phase] || '#4488ff',
                status: p.status || 'complete',
            }));

            const canvas = document.getElementById('canvas-gantt');
            if (canvas && events.length > 0) {
                Charts.drawGanttChart(canvas, events, {
                    title: 'Hyperloom Optimization Phases',
                    rowHeight: 24,
                });
            }
        } catch (_) {}
    },


    /* ============================================================
       BENCHMARK RESULTS
       ============================================================ */

    async loadBenchmarks() {
        try {
            const data = await API.get('/benchmark-runs');
            if (!data || !data.runs) return;

            const countBadge = document.getElementById('benchmark-count');
            if (countBadge) countBadge.textContent = data.runs.length + ' RUNS';

            this._renderBenchmarkCharts(data.runs);
            this._renderBenchmarkMetrics(data.runs);
        } catch (_) {}
    },

    async refreshBenchmarks() {
        await this.loadBenchmarks();
    },

    _getThroughput(r) { return r.throughput_tps || r.throughput || r.tokens_per_second || 0; },
    _getTTFT(r) { return r.ttft_p50 || r.ttft_median || r.ttft || 0; },
    _getLabel(r, i) {
        if (r.label) return r.label;
        const parts = [];
        if (r.max_num_seqs) parts.push('s' + r.max_num_seqs);
        parts.push(r.chunked_prefill ? 'CP' : 'noCP');
        if (r.tp) parts.push('TP' + r.tp);
        return parts.join('/') || ('R' + (i + 1));
    },

    _chartData: {},  // Store chart data for modal re-render

    _renderBenchmarkCharts(runs) {
        if (!runs.length) return;

        const throughputData = runs.map((r, i) => ({
            label: this._getLabel(r, i),
            value: this._getThroughput(r),
        }));
        this._chartData.throughput = throughputData;

        const canvas1 = document.getElementById('canvas-throughput');
        if (canvas1) {
            Charts.drawLineChart(canvas1, throughputData, {
                title: 'Throughput Over Runs',
                color: '#00c896',
                height: canvas1.parentElement?.clientHeight || 120,
            });
            canvas1.onclick = () => this.expandChart('throughput');
        }

        // Option B: filter out simulation/failed runs (TTFT = 0) — only real benchmarks
        const allTtftData = runs.map((r, i) => ({
            label: this._getLabel(r, i),
            value: this._getTTFT(r),
        }));
        const ttftData = allTtftData.filter(d => d.value > 0);
        this._chartData.ttft = ttftData;

        const canvas2 = document.getElementById('canvas-ttft');
        if (canvas2) {
            const countBadge = document.getElementById('benchmark-count');
            if (ttftData.length < allTtftData.length && countBadge) {
                countBadge.title = allTtftData.length + ' total runs, ' +
                    (allTtftData.length - ttftData.length) + ' simulation/zero-TTFT runs hidden';
            }
            if (ttftData.length === 0) {
                // All runs are simulations — show placeholder
                const ctx = canvas2.getContext('2d');
                const w = canvas2.parentElement?.clientWidth || 400;
                const h = canvas2.parentElement?.clientHeight || 120;
                canvas2.width = w; canvas2.height = h;
                ctx.fillStyle = '#0a0a14';
                ctx.fillRect(0, 0, w, h);
                ctx.fillStyle = '#555577';
                ctx.font = '11px Inter, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('No real benchmark runs yet (all TTFT = 0)', w / 2, h / 2);
                ctx.font = '9px Inter, sans-serif';
                ctx.fillText('Run a Real Run benchmark to see TTFT distribution', w / 2, h / 2 + 18);
            } else {
                Charts.drawBarChart(canvas2, ttftData, {
                    title: 'TTFT Distribution (ms) — ' + ttftData.length + ' real runs',
                    height: canvas2.parentElement?.clientHeight || 120,
                });
                canvas2.onclick = () => this.expandChart('ttft');
            }
        }
    },

    expandChart(type) {
        const modal = document.getElementById('chart-modal');
        const canvas = document.getElementById('canvas-modal-chart');
        const title = document.getElementById('chart-modal-title');
        if (!modal || !canvas) return;

        const data = this._chartData[type];
        if (!data || !data.length) return;

        modal.classList.add('open');

        // Render at large size after modal is visible
        requestAnimationFrame(() => {
            const w = canvas.parentElement?.clientWidth || 800;
            const h = 400;
            if (type === 'throughput') {
                title.textContent = 'Throughput (tok/s)';
                Charts.drawLineChart(canvas, data, {
                    title: 'Throughput Over Runs',
                    color: '#00c896',
                    height: h,
                });
            } else if (type === 'ttft') {
                title.textContent = 'TTFT Distribution (ms)';
                Charts.drawBarChart(canvas, data, {
                    title: 'TTFT Distribution',
                    height: h,
                });
            }
        });
    },

    closeChartModal(e) {
        const modal = document.getElementById('chart-modal');
        if (modal) modal.classList.remove('open');
    },

    _renderBenchmarkMetrics(runs) {
        if (!runs.length) return;

        const best = runs.reduce((a, b) =>
            this._getThroughput(b) > this._getThroughput(a) ? b : a
        , runs[0]);

        this._setText('metric-throughput', Math.round(this._getThroughput(best)));
        this._setText('metric-ttft', Math.round(this._getTTFT(best)));
        this._setText('metric-itl', (best.itl_p99 || best.itl_p50 || best.itl || 0).toFixed(1));
        this._setText('metric-tp', 'TP' + (best.tp || best.tensor_parallel || '--'));
    },


    /* ============================================================
       DEPLOYMENT PIPELINE
       ============================================================ */

    async loadDeployments() {
        try {
            const data = await API.get('/deployments');
            if (!data || !data.deployments || !data.deployments.length) return;

            const latest = data.deployments[0];
            this._renderPipeline(latest);
        } catch (_) {}
    },

    _renderPipeline(deploy) {
        if (!deploy) return;

        const stageOrder = ['pending', 'building', 'deploying', 'canary', 'promoted'];
        const currentStage = deploy.stage || deploy.status || 'pending';
        const currentIdx = stageOrder.indexOf(currentStage);

        stageOrder.forEach((stage, i) => {
            const el = document.getElementById('stage-' + stage);
            if (!el) return;
            el.classList.remove('completed', 'active', 'error');
            if (deploy.status === 'error' && i === currentIdx) {
                el.classList.add('error');
            } else if (i < currentIdx) {
                el.classList.add('completed');
            } else if (i === currentIdx) {
                el.classList.add(deploy.status === 'error' ? 'error' : 'active');
            }
        });

        const badge = document.getElementById('deploy-status');
        if (badge) badge.textContent = currentStage.toUpperCase();

        this._setText('deploy-model', deploy.model || '--');
        this._setText('deploy-framework', deploy.framework || '--');
        this._setText('deploy-tp', deploy.tp ? ('TP' + deploy.tp) : '--');
        this._setText('deploy-nodes', deploy.nodes?.join(', ') || '--');
        this._setText('deploy-started', deploy.started_at ? new Date(deploy.started_at).toLocaleTimeString() : '--');
    },

    deployBest() {
        if (!State.apiReady) return;
        this._sendChatCommand('Deploy the best optimized configuration from the last benchmark run. Use canary deployment.');
    },

    rollbackDeploy() {
        if (!State.apiReady) return;
        this._sendChatCommand('Rollback the current deployment to the previous stable configuration.');
    },


    /* ============================================================
       CHAT (sidebar)
       ============================================================ */

    async newChat() {
        if (!State.apiReady) return;
        if (this._ws) { this._ws.onmessage = null; this._ws.close(); this._ws = null; }

        const skill = document.getElementById('sel-skill')?.value || '';
        const mode = document.getElementById('sel-mode')?.value || 'autonomous';
        const data = await API.post('/conversations', { title: 'ERA Session', skill, mode });
        State.set('currentConvId', data.id);
        Chat.clear();

        const welcome = document.querySelector('.era-chat-welcome');
        if (welcome) welcome.remove();

        this.connectWebSocket(data.id);
        document.getElementById('chat-input')?.focus();
    },

    /* Build a context prefix from saved config so the agent never asks for details */
    _buildConfigContext() {
        const raw = localStorage.getItem('inferforge_era_config');
        if (!raw) return '';
        try {
            const c = JSON.parse(raw);
            const modelId = c.model === 'custom' ? (c.modelCustom || '') : (c.model || '');
            const parts = ['[CLUSTER CONFIG — use these values, do NOT ask for confirmation]'];
            if (c.head)        parts.push('Head node IP: ' + c.head);
            if (c.workers)     parts.push('Worker nodes: ' + c.workers);
            if (c.user)        parts.push('SSH user: ' + c.user);
            if (c.key)         parts.push('SSH key: ' + c.key);
            if (modelId)       parts.push('Model: ' + modelId);
            if (c.modelPath)   parts.push('Model path on node: ' + c.modelPath);
            if (c.framework)   parts.push('Framework: ' + c.framework);
            if (c.weightDtype) parts.push('Weight dtype: ' + c.weightDtype);
            if (c.kvDtype)     parts.push('KV dtype: ' + c.kvDtype);
            if (c.seqLen)      parts.push('Sequence length: ' + c.seqLen);
            if (c.ttft)        parts.push('SLA max TTFT: ' + c.ttft + ' ms');
            if (c.tpot)        parts.push('SLA max TPOT: ' + c.tpot + ' ms');
            if (c.throughput)  parts.push('SLA min throughput: ' + c.throughput + ' tok/s');
            if (c.e2e)         parts.push('SLA max E2E latency: ' + c.e2e + ' ms');
            const runType = document.getElementById('sel-runtype')?.value || 'simulation';
            parts.push('Run mode: ' + runType);
            return parts.join('\n') + '\n\n';
        } catch (_) { return ''; }
    },

    sendMessage() {
        const input = document.getElementById('chat-input');
        const text = (input?.value || '').trim();
        if (!text || State.isGenerating) return;
        if (!State.apiReady) {
            this._showToast('API NOT CONNECTED — check server');
            return;
        }

        this._markSessionActive();
        const fullContent = this._buildConfigContext() + text;

        if (!State.currentConvId) {
            this._newChatThenSend(text, fullContent);
            return;
        }

        if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
            this.connectWebSocket(State.currentConvId);
            input.value = '';
            this.autoResize(input);
            Chat.addUserBubble(text);
            this._setBusy();
            const check = setInterval(() => {
                if (this._ws && this._ws.readyState === WebSocket.OPEN) {
                    clearInterval(check);
                    this._ws.send(JSON.stringify({
                        type: 'message',
                        content: fullContent,
                        skill: document.getElementById('sel-skill')?.value || '',
                        mode: document.getElementById('sel-mode')?.value || 'autonomous',
                        run_type: document.getElementById('sel-runtype')?.value || 'simulation',
                    }));
                }
            }, 50);
            return;
        }

        const welcome = document.querySelector('.era-chat-welcome');
        if (welcome) welcome.remove();

        Chat.addUserBubble(text);
        input.value = '';
        this.autoResize(input);
        this._setBusy();

        this._ws.send(JSON.stringify({
            type: 'message',
            content: fullContent,
            skill: document.getElementById('sel-skill')?.value || '',
            mode: document.getElementById('sel-mode')?.value || 'autonomous',
            run_type: document.getElementById('sel-runtype')?.value || 'simulation',
        }));
    },

    async _newChatThenSend(displayText, fullContent) {
        if (!State.apiReady) return;
        if (this._ws) { this._ws.onmessage = null; this._ws.onclose = null; this._ws.close(); this._ws = null; }

        const skill = document.getElementById('sel-skill')?.value || '';
        const mode = document.getElementById('sel-mode')?.value || 'autonomous';
        const data = await API.post('/conversations', { title: displayText.slice(0, 60), skill, mode });
        State.set('currentConvId', data.id);
        Chat.clear();

        const welcome = document.querySelector('.era-chat-welcome');
        if (welcome) welcome.remove();

        this.connectWebSocket(data.id);

        await new Promise((resolve, reject) => {
            const check = setInterval(() => {
                if (this._ws && this._ws.readyState === WebSocket.OPEN) { clearInterval(check); resolve(); }
            }, 50);
            setTimeout(() => { clearInterval(check); reject(new Error('WebSocket timeout')); }, 5000);
        });

        Chat.addUserBubble(displayText);
        document.getElementById('chat-input').value = '';
        this._setBusy();
        this._ws.send(JSON.stringify({ type: 'message', content: fullContent, skill, mode }));
    },

    _sendChatCommand(text) {
        const input = document.getElementById('chat-input');
        if (input) input.value = text;
        this.sendMessage();
    },

    /**
     * Memory Calc always runs as SIMULATION — overrides the run-type dropdown.
     * Pure local math only: no SSH, no Docker, no GPU access needed.
     */
    memoryCalcCommand() {
        const dropdown = document.getElementById('sel-runtype');
        const prev = dropdown ? dropdown.value : 'simulation';
        // Force simulation for memory calc regardless of current setting
        if (dropdown) dropdown.value = 'simulation';
        this.quickCommand(
            '[RUN TYPE: SIMULATION — memory analysis only. Do NOT launch Docker or SSH for GPU detection. ' +
            'Use GPU info already in the cluster config.] ' +
            'Run the memory calculator and show the FULL report with all sections from report_format.md — ' +
            'show every formula step by step including weight memory, KV cache per token, KV cache per request, ' +
            'overhead, KV budget, max batch size, HBM visualization, parallelism table, batch sweep, ' +
            'and recommended vLLM launch command.'
        );
        // Restore original run type after message is queued
        setTimeout(() => { if (dropdown) dropdown.value = prev; }, 100);
    },

    quickCommand(text) {
        const input = document.getElementById('chat-input');
        if (input) {
            input.value = text;
            this.autoResize(input);
            input.focus();
        }
        this.sendMessage();
    },

    /** Direct memory calculator — calls API without agent, instant results */
    async runMemoryCalc() {
        this._markSessionActive();

        // Get config
        const raw = localStorage.getItem('inferforge_era_config');
        if (!raw) {
            this._showToast('CONFIGURE CLUSTER FIRST');
            return;
        }
        const cfg = JSON.parse(raw);
        const modelId = cfg.model === 'custom' ? (cfg.modelCustom || '') : (cfg.model || '');
        if (!modelId) {
            this._showToast('SELECT A MODEL FIRST');
            return;
        }

        // Map model name to registry key — fetch registry and fuzzy match
        let modelKey = '';
        try {
            const models = await API.get('/models');
            const keys = (Array.isArray(models) ? models : []).map(m => m.key || m);
            // Normalize the user's model name for matching
            const norm = modelId.split('/').pop().toLowerCase()
                .replace(/instruct|chat|base/gi, '').replace(/meta-?llama-?/i, 'llama-')
                .replace(/--+/g, '-').replace(/-$/, '').replace(/_/g, '-').trim();
            // Try exact match first
            modelKey = keys.find(k => k === norm) || '';
            // Try matching by param size (e.g., "70b" in both)
            if (!modelKey) {
                const sizeMatch = norm.match(/(\d+)b/);
                const familyMatch = norm.match(/^([a-z]+(?:-[a-z]+)?)/);
                if (sizeMatch && familyMatch) {
                    modelKey = keys.find(k =>
                        k.includes(sizeMatch[1] + 'b') && k.startsWith(familyMatch[1])
                    ) || '';
                }
            }
            // Last resort: closest substring match
            if (!modelKey) {
                modelKey = keys.find(k => norm.includes(k) || k.includes(norm)) || norm;
            }
        } catch (_) {
            modelKey = modelId.split('/').pop().toLowerCase()
                .replace(/instruct|chat|base/gi, '').replace(/meta-?llama-?/i, 'llama-')
                .replace(/--+/g, '-').replace(/-$/, '').trim();
        }

        const welcome = document.querySelector('.era-chat-welcome');
        if (welcome) welcome.remove();

        // Get GPU info from fleet
        let gpuPlatform = 'MI300X';
        let gpuCount = 8;
        try {
            const fleet = await API.get('/fleet/nodes');
            if (fleet && fleet.nodes && fleet.nodes.length > 0) {
                const head = fleet.nodes.find(n => n.ip === cfg.head) || fleet.nodes[0];
                gpuPlatform = head.gpu_model || head.gpu_platform || 'MI300X';
                gpuCount = head.gpu_count || 8;
            }
        } catch (_) {}

        Chat.addUserBubble('Run memory calculator simulation for ' + modelId);
        Chat.startAssistantBubble();
        Chat.appendToCurrentMsg('Running memory calculator for **' + modelId + '** on **' + gpuCount + '× ' + gpuPlatform + '**...\n\n');

        try {
            const dtypeMap = { bfloat16: 'bf16', float16: 'fp16', float32: 'fp32' };
            const dtype = dtypeMap[cfg.weightDtype] || cfg.weightDtype || 'bf16';
            const result = await API.post('/calculate', {
                model: modelKey,
                gpu: gpuPlatform,
                gpu_count: gpuCount,
                dtype: dtype,
                kv_dtype: (!cfg.kvDtype || cfg.kvDtype === 'same') ? null : cfg.kvDtype,
                seq_len: parseInt(cfg.seqLen) || 4096,
            });

            // Format full report (matches agent report_format.md style)
            const r = result;
            const hbm = r.hbm_per_gpu_gb;
            const seqLen = parseInt(cfg.seqLen) || 4096;
            let md = '## InferForge Memory Analysis — Simulation Report\n\n';

            // Section 1: Header
            md += '### 1. Header\n\n';
            md += '| Field | Value |\n|-------|-------|\n';
            md += '| Model | ' + (r.model || modelId) + ' (' + r.params_billions + 'B, ' + (r.architecture || 'dense') + ') |\n';
            md += '| Attention | ' + (r.attention_type || 'GQA').toUpperCase() + ' |\n';
            md += '| GPU Platform | ' + r.gpu_count + '× AMD Instinct ' + r.gpu_platform + ' |\n';
            md += '| HBM per GPU | ' + hbm + ' GB (HBM3) |\n';
            md += '| Total HBM | ' + r.total_hbm_gb + ' GB |\n';
            md += '| Weight dtype | ' + (r.weight_dtype || 'bf16') + ' |\n';
            md += '| KV dtype | ' + (r.kv_dtype || r.weight_dtype || 'bf16') + ' |\n';
            md += '| Sequence Length | ' + seqLen.toLocaleString() + ' tokens |\n';
            md += '| Run Mode | Simulation (no GPUs touched) |\n\n';

            // Section 2: Formulas Applied
            md += '### 2. Formulas Applied\n\n';
            md += '| Component | Formula | Result |\n|-----------|---------|--------|\n';
            md += '| Weight Memory | ' + r.params_billions + 'B params x 2 bytes (bf16) | **' + r.weight_memory_gb + ' GB** total |\n';
            md += '| KV per Token | 2 x layers x kv_heads x head_dim x 2 bytes | ' + (r.kv_per_token_bytes || 0).toLocaleString() + ' bytes/token |\n';
            md += '| KV per Request | kv_per_token x ' + seqLen.toLocaleString() + ' tokens | **' + r.kv_per_request_gb + ' GB**/req |\n';
            md += '| Overhead | 10% x HBM per GPU | ' + r.overhead_gb + ' GB |\n';
            const refConfig = r.recommended || (r.valid_configs && r.valid_configs[0]);
            if (refConfig) {
                md += '| KV Budget (TP=' + refConfig.tp + ') | ' + hbm + ' - ' + refConfig.weight_per_gpu_gb + ' - ' + r.overhead_gb + ' | **' + refConfig.kv_budget_per_gpu_gb + ' GB** |\n';
                md += '| Max Batch (TP=' + refConfig.tp + ') | floor(' + refConfig.kv_budget_per_gpu_gb + ' / ' + refConfig.kv_per_request_gb + ') | **' + refConfig.max_batch_size + '** concurrent reqs |\n';
            }
            md += '\n';

            // Section 3: Parallelism Configurations
            md += '### 3. Parallelism Configurations\n\n';
            md += '| TP | PP | DP | Weight/GPU | KV Budget | Max Batch | HBM Util | Best For |\n';
            md += '|:--:|:--:|:--:|:---------:|:---------:|:---------:|:--------:|:---------|\n';
            for (const c of (r.valid_configs || [])) {
                const util = ((c.weight_per_gpu_gb + r.overhead_gb) / hbm * 100).toFixed(1);
                const isRec = r.recommended && c.tp === r.recommended.tp && c.pp === r.recommended.pp && c.dp === r.recommended.dp;
                let bestFor = '';
                if (isRec) bestFor = 'Recommended';
                else if (c.tp === r.gpu_count) bestFor = 'Min TTFT';
                else if (c.dp >= 4) bestFor = 'Max Throughput';
                else if (parseFloat(util) > 60) bestFor = 'Tight KV';
                md += '| ' + c.tp + ' | ' + c.pp + ' | ' + c.dp;
                md += ' | ' + c.weight_per_gpu_gb + ' GB | ' + c.kv_budget_per_gpu_gb + ' GB';
                md += ' | ' + c.max_batch_size + ' | ' + util + '% | ' + bestFor + ' |\n';
            }

            // Section 4: HBM Visualization
            md += '\n### 4. HBM Visualization\n\n';
            md += '```\n' + r.gpu_platform + ' HBM: ' + hbm + ' GB per GPU\n\n';
            const vizConfigs = (r.valid_configs || []).filter(c => c.pp <= 1).slice(0, 4);
            for (const c of vizConfigs) {
                const isRec = r.recommended && c.tp === r.recommended.tp && c.pp === r.recommended.pp;
                const wPct = c.weight_per_gpu_gb / hbm;
                const oPct = r.overhead_gb / hbm;
                const kvPct = c.kv_budget_per_gpu_gb / hbm;
                const barLen = 40;
                const wBar = Math.round(wPct * barLen);
                const oBar = Math.round(oPct * barLen);
                const kvBar = Math.round(kvPct * barLen);
                md += '  TP=' + c.tp + '/DP=' + c.dp + (isRec ? ' ★ RECOMMENDED' : '') + '\n';
                md += '  Weights   [' + '█'.repeat(wBar) + '░'.repeat(barLen - wBar) + ']  ' + c.weight_per_gpu_gb + ' GB\n';
                md += '  Overhead  [' + '█'.repeat(oBar) + '░'.repeat(barLen - oBar) + ']  ' + r.overhead_gb + ' GB\n';
                md += '  KV Budget [' + '░'.repeat(kvBar) + ' '.repeat(barLen - kvBar) + ']  ' + c.kv_budget_per_gpu_gb + ' GB\n';
                md += '  → Max ' + c.max_batch_size + ' concurrent reqs\n\n';
            }
            md += '```\n\n';

            // Section 5: Batch Sweep
            if (r.batch_sweep && r.batch_sweep.length > 0) {
                md += '### 5. Batch Sweep (recommended config)\n\n';
                md += '| max-num-seqs | Chunked Prefill | KV Used | KV Util | Est. Throughput | Label |\n';
                md += '|:---:|:---:|:---:|:---:|:---:|:---:|\n';
                for (const b of r.batch_sweep) {
                    const cp = b.chunked_prefill ? 'ON' : 'OFF';
                    const label = b.recommendation || '';
                    md += '| ' + b.max_num_seqs + ' | ' + cp + ' | ' + b.kv_used_gb.toFixed(1) + ' GB';
                    md += ' | ' + b.kv_util_pct.toFixed(1) + '% | ~' + b.est_throughput_tps + ' tok/s | ' + label + ' |\n';
                }
                md += '\n';
            }

            // Section 6: Recommended Config + Launch Args
            if (r.recommended) {
                const rec = r.recommended;
                const modelPath = cfg.modelPath || cfg.modelCustom || modelId;
                md += '### 6. Recommended Configuration\n\n';
                md += '**TP=' + rec.tp + ' / PP=' + rec.pp + ' / DP=' + rec.dp + '**';
                if (rec.dp > 1) md += ' — ' + rec.dp + ' independent replicas';
                md += '\n\n';
                md += '| Attribute | Value |\n|-----------|-------|\n';
                md += '| Weight per GPU | ' + rec.weight_per_gpu_gb + ' GB / ' + hbm + ' GB (' + (rec.weight_per_gpu_gb / hbm * 100).toFixed(0) + '%) |\n';
                md += '| KV Budget per GPU | ' + rec.kv_budget_per_gpu_gb + ' GB |\n';
                md += '| Max Concurrent Reqs | ' + rec.max_batch_size + ' |\n';
                md += '| Est. Throughput | ~' + rec.est_output_tps + ' tok/s |\n\n';
                md += '**vLLM launch command:**\n```bash\npython3 -m vllm.entrypoints.openai.api_server \\\n';
                md += '  --model ' + modelPath + ' \\\n';
                md += '  --tensor-parallel-size ' + rec.tp + ' \\\n';
                md += '  --dtype bfloat16 \\\n';
                md += '  --max-num-seqs 128 \\\n';
                md += '  --port 8000\n```\n\n';
                md += 'For latency-optimized (lower TTFT p99):\n```\n  --max-num-seqs 64 --enable-chunked-prefill\n```\n';
            }

            // Warnings
            if (r.model_warning) md += '\n> ' + r.model_warning + '\n';
            md += '\n*Simulation — run a Real Run for measured TTFT/throughput.*\n';

            Chat.appendToCurrentMsg(md);
            Chat.finalizeCurrentMsg();
            this._showToast('CALC COMPLETE');
        } catch (e) {
            // Extract readable error message from various error shapes
            let errMsg = '';
            if (typeof e === 'string') errMsg = e;
            else if (e?.detail) errMsg = typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail);
            else if (e?.message) errMsg = e.message;
            else if (e?.statusText) errMsg = e.statusText;
            else try { errMsg = JSON.stringify(e); } catch (_) { errMsg = String(e); }

            // Fallback to agent chat for model key issues
            if (errMsg.includes('422') || errMsg.includes('non-zero') || errMsg.includes('not found')) {
                Chat.appendToCurrentMsg('Direct calc key "' + modelKey + '" not in registry. Falling back to agent...\n');
                Chat.finalizeCurrentMsg();
                this.quickCommand('Run memory calculator simulation for ' + modelId + ' and show max batch size');
            } else {
                Chat.appendToCurrentMsg('**Error:** ' + errMsg + '\n');
                Chat.finalizeCurrentMsg();
            }
        }
    },


    /* ============================================================
       WEBSOCKET
       ============================================================ */

    connectWebSocket(cid) {
        if (this._ws && this._ws.readyState === WebSocket.OPEN && this._ws._cid === cid) return;
        if (this._ws) { this._ws.onmessage = null; this._ws.onclose = null; this._ws.close(); this._ws = null; }

        this._ws = API.connectWebSocket('/ws/chat/' + cid, {
            onOpen: () => {},
            onClose: () => { this._setIdle(); },
            onError: () => {},
            onMessage: (data) => this.handleEvent(data),
        });
        this._ws._cid = cid;
    },

    handleEvent(ev) {
        if (!State.currentConvId) return;

        switch (ev.type) {
            case 'connected':
                this._replayJobWasRunning = !!ev.job_running;
                if (ev.job_running) this._setBusy();
                break;

            case 'replay_start':
                this._inReplay = true;
                break;

            case 'replay_end':
                this._inReplay = false;
                if (!this._replayJobWasRunning) {
                    Chat.finalizeCurrentMsg();
                    this._setIdle();
                    if (State.currentConvId) {
                        API.get('/conversations/' + State.currentConvId).then(data => {
                            Chat.clear();
                            for (const msg of (data.messages || [])) {
                                if (msg.role === 'user') Chat.addUserBubble(msg.content);
                                else if (msg.role === 'assistant') Chat.addAssistantBubble(msg.content, msg.tool_calls);
                            }
                            Chat.scrollToBottom(true);
                        });
                    }
                }
                break;

            case 'text_delta':
                if (!Chat.currentMsgEl) Chat.startAssistantBubble();
                // Repetition loop detector: if same phrase repeats 5+ times, truncate
                if (!this._repTracker) this._repTracker = { buf: '', count: 0, last: '' };
                this._repTracker.buf += ev.content;
                if (this._repTracker.buf.length > 200) {
                    const chunk = this._repTracker.buf.slice(-150);
                    // Find repeated phrase (30+ chars appearing 3+ times)
                    const repMatch = chunk.match(/(.{30,}?)\1{2,}/);
                    if (repMatch) {
                        this._repTracker.count++;
                        if (this._repTracker.count >= 2) {
                            Chat.appendToCurrentMsg('\n\n**[Loop detected — output truncated. Click STOP and retry.]**');
                            this._repTracker = { buf: '', count: 0, last: '' };
                            break;
                        }
                    }
                    this._repTracker.buf = this._repTracker.buf.slice(-300);
                }
                Chat.appendToCurrentMsg(ev.content);
                break;

            case 'tool_use_start':
                if (Chat.currentToolEl) {
                    const prevToggle = Chat.currentToolEl.querySelector('.tool-toggle');
                    const prevBody = Chat.currentToolEl.querySelector('.tool-body');
                    if (prevToggle) prevToggle.classList.remove('open');
                    if (prevBody) prevBody.classList.remove('visible');
                }
                if (!Chat.currentMsgEl) Chat.startAssistantBubble();
                Chat.addToolBlock(Chat.currentMsgEl, ev.tool_name, ev.input);
                break;

            case 'tool_output_line':
                Chat.appendToolOutput(Chat.currentToolEl, ev.content);
                break;

            case 'tool_use_end':
                Chat.finalizeToolBlock(Chat.currentToolEl, ev.exit_code);
                Chat.currentToolEl = null;
                break;

            case 'message_complete':
                this._repTracker = null;
                Chat.finalizeCurrentMsg();
                this._setIdle();
                this._refreshAllPanels();
                this._tryParseGpuFromChat();
                this._tryParseBenchmarkFromChat();
                break;

            case 'error':
                if (Chat.currentMsgEl) {
                    Chat.appendToCurrentMsg('\n\n**Error:** ' + ev.content);
                    Chat.finalizeCurrentMsg();
                } else {
                    Chat.addAssistantBubble('**Error:** ' + ev.content);
                }
                this._setIdle();
                break;

            case 'inference_update':
            case 'inference_state_update':
                if (ev.data) {
                    this._updateHeaderStats(ev.data);
                    this._autoUpsertFleetNode(ev.data);
                    this.refreshTelemetry();
                }
                break;
        }
    },


    /* ============================================================
       JOB CONTROL
       ============================================================ */

    stopJob() {
        if (!State.currentConvId) return;

        // 1. Close WebSocket immediately — stops ALL streaming to UI right now
        if (this._ws) {
            this._ws.onmessage = null;  // block any in-flight events
            this._ws.onclose = null;
            try { this._ws.close(); } catch (_) {}
            this._ws = null;
        }

        // 2. Cancel backend task via HTTP (kills agent + Docker containers)
        API.post('/cancel/' + State.currentConvId).catch(() => {});

        // 3. Update UI immediately
        Chat.finalizeCurrentMsg();
        const container = Chat.container();
        if (container) {
            const notice = document.createElement('div');
            notice.className = 'msg assistant';
            notice.style.cssText = 'border-color: var(--red); background: rgba(255, 68, 102, 0.08);';
            notice.innerHTML = '<strong>Job stopped by user</strong>';
            container.appendChild(notice);
            Chat.scrollToBottom(true);
        }

        this._setIdle();
    },

    _setBusy() {
        State.set('isGenerating', true);
        const sendBtn = document.getElementById('btn-send');
        const stopBtn = document.getElementById('btn-stop');
        if (sendBtn) sendBtn.disabled = true;
        if (stopBtn) stopBtn.classList.add('visible');

        const beacon = document.getElementById('era-status-beacon');
        if (beacon) beacon.className = 'era-status-beacon busy';

        const si = document.getElementById('era-session-indicator');
        if (si) si.classList.add('active');

        Chat.showThinking();
    },

    _setIdle() {
        State.set('isGenerating', false);
        const sendBtn = document.getElementById('btn-send');
        const stopBtn = document.getElementById('btn-stop');
        if (sendBtn) sendBtn.disabled = !State.apiReady;
        if (stopBtn) stopBtn.classList.remove('visible');

        const beacon = document.getElementById('era-status-beacon');
        if (beacon) beacon.className = 'era-status-beacon ' + (State.apiReady ? 'online' : 'error');

        Chat.hideThinking();
        document.querySelectorAll('.running-badge').forEach(b => b.remove());
    },


    /* ============================================================
       PANEL FOCUS
       ============================================================ */

    focusPanel(index) {
        const panels = ['panel-telemetry', 'panel-timeline', 'panel-benchmarks', 'panel-deployments'];
        panels.forEach(id => document.getElementById(id)?.classList.remove('focused'));

        if (index >= 1 && index <= 4) {
            const target = document.getElementById(panels[index - 1]);
            if (target) {
                target.classList.add('focused');
                this._focusedPanel = index;

                setTimeout(() => {
                    target.classList.remove('focused');
                    this._focusedPanel = null;
                }, 3000);
            }
        }
    },


    /* ============================================================
       KEYBOARD SHORTCUTS
       ============================================================ */

    initKeyboard() {
        document.addEventListener('keydown', (e) => {
            const input = document.getElementById('chat-input');
            const isInputFocused = document.activeElement === input;

            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                this.sendMessage();
                return;
            }

            if (e.key === 'Escape') {
                if (State.isGenerating) {
                    this.stopJob();
                } else if (isInputFocused) {
                    input.blur();
                }
                return;
            }

            if (isInputFocused) return;

            if (e.key === '/') {
                e.preventDefault();
                if (input) input.focus();
                return;
            }

            if (e.key >= '1' && e.key <= '4') {
                e.preventDefault();
                this.focusPanel(parseInt(e.key));
                return;
            }

            if (e.key === 'r' || e.key === 'R') {
                e.preventDefault();
                this._refreshAllPanels();
                return;
            }
        });
    },

    handleKey(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            this.sendMessage();
        }
    },

    autoResize(el) {
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 80) + 'px';
    },


    /* ============================================================
       REFRESH ALL
       ============================================================ */

    _refreshAllPanels() {
        this._markSessionActive();
        this.refreshTelemetry();
        this.loadTimeline();
        this.loadBenchmarks();
        this.loadDeployments();
    },


    /* ============================================================
       DASHBOARD RESET & HISTORY
       ============================================================ */

    /** Mark session as active (called when user sends first message or Detect GPUs) */
    _markSessionActive() {
        if (!this._sessionActive) {
            this._sessionActive = true;
            sessionStorage.setItem('inferforge_session_active', '1');
            // Start telemetry polling now that session is active
            if (!this._telemetryTimer) {
                this.loadFleet();
                this._telemetryTimer = setInterval(() => this.refreshTelemetry(), 10000);
            }
        }
    },

    /** Show empty/clean GPU telemetry panel */
    _showEmptyTelemetry() {
        const grid = document.getElementById('telemetry-grid');
        if (grid) {
            grid.innerHTML = '<div class="era-empty-panel">' +
                '<div class="era-empty-label">AWAITING NODE DATA</div>' +
                '<div class="era-empty-hint">Configure cluster and run GPU detection</div></div>';
        }
        this._setText('telemetry-status', 'STANDBY');
        this._setText('era-node-count', '0');
        this._setText('era-gpu-count', '0');

        // Clear inline heatmap
        const ih = document.getElementById('inline-heatmap');
        if (ih) ih.innerHTML = '';
        // Clear telemetry chart
        const tc = document.getElementById('canvas-telemetry');
        if (tc) { const ctx = tc.getContext('2d'); ctx.clearRect(0, 0, tc.width, tc.height); }
        this._telemetryHistory = { labels: [], nodes: {}, gpuSnapshot: {}, gpuHistory: {} };
    },

    /** Show empty/clean benchmark charts and metrics */
    _showEmptyBenchmarks() {
        // Reset canvas dimensions — this wipes all drawn content regardless of size
        for (const id of ['canvas-throughput', 'canvas-ttft']) {
            const c = document.getElementById(id);
            if (c) { c.width = c.width; c.style.width = ''; c.style.height = ''; }
        }
        this._setText('metric-throughput', '--');
        this._setText('metric-ttft', '--');
        this._setText('metric-itl', '--');
        this._setText('metric-tp', '--');
        this._setText('benchmark-count', '0 RUNS');
        this._chartData = {};
    },

    /** Show empty/clean deployment pipeline */
    _showEmptyDeployments() {
        const stages = ['pending', 'building', 'deploying', 'canary', 'promoted'];
        stages.forEach(s => {
            const el = document.getElementById('stage-' + s);
            if (el) el.classList.remove('completed', 'active', 'error');
        });
        this._setText('deploy-status', 'IDLE');
        this._setText('deploy-model', '--');
        this._setText('deploy-framework', '--');
        this._setText('deploy-tp', '--');
        this._setText('deploy-nodes', '--');
        this._setText('deploy-started', '--');
    },

    /** Full dashboard reset — clears ALL panels back to empty state */
    resetDashboard() {
        // Clear session flag and stop telemetry polling
        this._sessionActive = false;
        sessionStorage.removeItem('inferforge_session_active');
        if (this._telemetryTimer) {
            clearInterval(this._telemetryTimer);
            this._telemetryTimer = null;
        }

        // Reset ALL panels
        this._showEmptyTelemetry();
        this._showEmptyBenchmarks();
        this._showEmptyDeployments();

        // Reset timeline
        const canvas = document.getElementById('canvas-gantt');
        if (canvas) { const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, canvas.width, canvas.height); }
        this._setText('timeline-phase', '--');
        const sel = document.getElementById('timeline-session-select');
        if (sel) sel.innerHTML = '<option value="">Select Session</option>';

        // Reset session indicator
        const si = document.getElementById('era-session-indicator');
        if (si) si.classList.remove('active');
        this._setText('era-session-label', 'NO ACTIVE SESSION');

        this._showToast('DASHBOARD RESET');
    },

    /** Load historical benchmark data into charts (archive view) */
    loadBenchmarkHistory() {
        this._markSessionActive();
        this.loadBenchmarks();
        this.loadDeployments();
        this.loadSessions();
        this._showToast('HISTORY LOADED');
    },


    /* ============================================================
       CONFIG DRAWER
       ============================================================ */

    toggleConfig() {
        const drawer = document.getElementById('era-config-drawer');
        if (!drawer) return;
        drawer.classList.toggle('open');
        const btn = document.getElementById('btn-config');
        if (btn) btn.style.color = drawer.classList.contains('open') ? 'var(--cyan)' : '';
    },

    selectFramework(fw) {
        document.querySelectorAll('.era-fw-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.fw === fw);
        });
    },

    _getSelectedFramework() {
        const active = document.querySelector('.era-fw-btn.active');
        return active ? active.dataset.fw : 'vllm';
    },

    saveConfig() {
        const cfg = {
            head:       document.getElementById('cfg-head')?.value.trim() || '',
            workers:    document.getElementById('cfg-workers')?.value.trim() || '',
            user:       document.getElementById('cfg-user')?.value.trim() || '',
            key:        document.getElementById('cfg-key')?.value.trim() || '',
            model:      document.getElementById('cfg-model')?.value || '',
            modelCustom: document.getElementById('cfg-model-custom')?.value.trim() || '',
            modelPath:  document.getElementById('cfg-model-path')?.value.trim() || '',
            framework:  this._getSelectedFramework(),
            weightDtype: document.getElementById('cfg-weight-dtype')?.value || 'bfloat16',
            kvDtype:    document.getElementById('cfg-kv-dtype')?.value || 'same',
            seqLen:     document.getElementById('cfg-seq-len')?.value || '4096',
            ttft:       document.getElementById('cfg-ttft')?.value || '',
            tpot:       document.getElementById('cfg-tpot')?.value || '',
            throughput: document.getElementById('cfg-throughput')?.value || '',
            e2e:        document.getElementById('cfg-e2e')?.value || '',
        };
        localStorage.setItem('inferforge_era_config', JSON.stringify(cfg));

        // Broadcast config to Classic/Nova via shared API endpoint
        const modelId = cfg.model === 'custom' ? cfg.modelCustom : cfg.model;
        const payload = {
            head_ip: cfg.head,
            workers: cfg.workers,
            ssh_user: cfg.user,
            ssh_key: cfg.key,
            model: modelId,
            model_path: cfg.modelPath,
            framework: cfg.framework,
            weight_dtype: cfg.weightDtype,
            kv_dtype: cfg.kvDtype,
            seq_len: parseInt(cfg.seqLen) || 4096,
            sla_ttft: cfg.ttft ? parseInt(cfg.ttft) : null,
            sla_tpot: cfg.tpot ? parseInt(cfg.tpot) : null,
            sla_throughput: cfg.throughput ? parseInt(cfg.throughput) : null,
            sla_e2e: cfg.e2e ? parseInt(cfg.e2e) : null,
        };
        API.post('/config/cluster', payload).catch(() => {});

        // Auto-register head node and workers in fleet DB (SSH creds only — never overwrite GPU data)
        const registerNode = (ip) => {
            if (!ip) return;
            const hostname = ip.replace(/[^a-zA-Z0-9.\-]/g, '') || ip;
            API.post('/fleet/nodes/upsert', {
                hostname: hostname,
                ip_address: ip,
                ssh_user: cfg.user || null,
            }).catch(() => {});
        };
        registerNode(cfg.head);
        (cfg.workers || '').split(',').forEach(w => registerNode(w.trim()));

        // Refresh telemetry panel immediately after registering
        setTimeout(() => this.loadFleet(), 800);

        this.toggleConfig();
        this._showToast('CONFIG SAVED');
    },

    _loadConfigFromStorage() {
        const raw = localStorage.getItem('inferforge_era_config');
        if (!raw) return;
        try {
            const cfg = JSON.parse(raw);
            this._setVal('cfg-head', cfg.head);
            this._setVal('cfg-workers', cfg.workers);
            this._setVal('cfg-user', cfg.user);
            this._setVal('cfg-key', cfg.key);
            this._setVal('cfg-model', cfg.model);
            this._setVal('cfg-model-custom', cfg.modelCustom);
            this._setVal('cfg-model-path', cfg.modelPath);
            this._setVal('cfg-weight-dtype', cfg.weightDtype);
            this._setVal('cfg-kv-dtype', cfg.kvDtype);
            this._setVal('cfg-seq-len', cfg.seqLen);
            this._setVal('cfg-ttft', cfg.ttft);
            this._setVal('cfg-tpot', cfg.tpot);
            this._setVal('cfg-throughput', cfg.throughput);
            this._setVal('cfg-e2e', cfg.e2e);
            if (cfg.framework) this.selectFramework(cfg.framework);
            // Show custom model row if needed
            if (cfg.model === 'custom') {
                const row = document.getElementById('cfg-custom-model-row');
                if (row) row.style.display = '';
            }
        } catch (_) {}
    },

    _setVal(id, val) {
        const el = document.getElementById(id);
        if (el && val !== undefined && val !== null) el.value = val;
    },

    _showToast(msg) {
        const t = document.createElement('div');
        t.className = 'era-config-toast';
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 2200);
    },


    /* ============================================================
       CHAT HISTORY
       ============================================================ */

    async loadHistory() {
        try {
            const raw = await API.get('/conversations');
            const convs = raw?.conversations || (Array.isArray(raw) ? raw : null);
            if (!convs || !convs.length) {
                this._showToast('NO HISTORY');
                return;
            }
            this._markSessionActive();
            const latest = convs[0];
            State.set('currentConvId', latest.id);
            Chat.clear();

            const welcome = document.querySelector('.era-chat-welcome');
            if (welcome) welcome.remove();

            const conv = await API.get('/conversations/' + latest.id);
            for (const msg of (conv.messages || [])) {
                if (msg.role === 'user') Chat.addUserBubble(msg.content);
                else if (msg.role === 'assistant') Chat.addAssistantBubble(msg.content);
            }
            Chat.scrollToBottom(true);
            this.connectWebSocket(latest.id);
            this._showToast('HISTORY LOADED');
        } catch (e) {
            this._showToast('LOAD FAILED');
        }
    },


    /* ============================================================
       UTILITIES
       ============================================================ */

    _tryParseBenchmarkFromChat() {
        const msgs = document.querySelectorAll('.era-chat-messages .msg.assistant');
        if (!msgs.length) return;
        const lastMsg = msgs[msgs.length - 1]?.textContent || '';

        // Only parse if this looks like a benchmark result message
        if (!lastMsg.match(/tok\/s/i) || !lastMsg.match(/TTFT|throughput/i)) return;

        // Try to find the config from localStorage
        const raw = localStorage.getItem('inferforge_era_config');
        let cfg = {};
        try { cfg = raw ? JSON.parse(raw) : {}; } catch (_) {}
        const modelId = cfg.model === 'custom' ? (cfg.modelCustom || '') : (cfg.model || '');

        // Parse benchmark table rows: look for patterns like "570.3 tok/s" and "98.6 ms"
        // Match lines with Config A/B/C or similar patterns
        const configPatterns = [
            // "Config A ... 570.3 tok/s ... 98.6 ms ... 247.7 ms ... 19.1 ms ... 14.6 ms"
            /(?:Config\s*)?([A-C])\s*\|?\s*(\d+)\s*\|?\s*(ON|OFF|✅|❌)[^|]*\|?\s*([\d,.]+)\s*tok\/s\s*\|?\s*([\d,.]+)\s*ms\s*\|?\s*([\d,.]+)\s*ms\s*\|?\s*([\d,.]+)\s*ms\s*\|?\s*([\d,.]+)\s*ms/gi,
        ];

        // Simpler fallback: extract throughput + TTFT from any text
        const throughputMatch = lastMsg.match(/([\d,.]+)\s*tok\/s/);
        const ttftP50Match = lastMsg.match(/TTFT\s*(?:p50)?[:\s]*([\d,.]+)\s*ms/i);
        const ttftP99Match = lastMsg.match(/TTFT\s*p99[:\s]*([\d,.]+)\s*ms/i);
        const tpotMatch = lastMsg.match(/TPOT\s*(?:p50)?[:\s]*([\d,.]+)\s*ms/i);
        const itlMatch = lastMsg.match(/ITL\s*(?:p50)?[:\s]*([\d,.]+)\s*ms/i);
        const gpuMatch = lastMsg.match(/(\d+)\s*[x×]\s*(?:AMD\s+Instinct\s+)?(MI\d+\w*)/i);
        const tpMatch = lastMsg.match(/TP[=:\s]*(\d+)/i);

        // Try to extract individual config rows from table-like text
        const rows = [];
        // Match table rows: A|64|ON|570.3 tok/s|98.6 ms|...
        const tableRegex = /([A-C])\s+(\d+)\s+(✅\s*ON|❌\s*OFF|ON|OFF)\s+([\d,.]+)\s*tok\/s\s+([\d,.]+)\s*ms\s+([\d,.]+)\s*ms\s+([\d,.]+)\s*ms\s+([\d,.]+)\s*ms/gi;
        let m;
        while ((m = tableRegex.exec(lastMsg)) !== null) {
            rows.push({
                label: 'Config ' + m[1],
                max_num_seqs: parseInt(m[2]),
                chunked_prefill: m[3].includes('ON') ? 1 : 0,
                throughput_tps: parseFloat(m[4].replace(',', '')),
                ttft_p50: parseFloat(m[5].replace(',', '')),
                ttft_p99: parseFloat(m[6].replace(',', '')),
                tpot_p50: parseFloat(m[7].replace(',', '')),
                itl_p50: parseFloat(m[8].replace(',', '')),
            });
        }

        // If no table rows found, try to extract at least one result
        if (rows.length === 0 && throughputMatch) {
            rows.push({
                label: 'Benchmark',
                throughput_tps: parseFloat(throughputMatch[1].replace(',', '')),
                ttft_p50: ttftP50Match ? parseFloat(ttftP50Match[1].replace(',', '')) : null,
                ttft_p99: ttftP99Match ? parseFloat(ttftP99Match[1].replace(',', '')) : null,
                tpot_p50: tpotMatch ? parseFloat(tpotMatch[1].replace(',', '')) : null,
                itl_p50: itlMatch ? parseFloat(itlMatch[1].replace(',', '')) : null,
            });
        }

        if (rows.length === 0) return;

        const gpuPlatform = gpuMatch ? gpuMatch[2].toUpperCase() : (cfg.gpuPlatform || 'MI300X');
        const gpuCount = gpuMatch ? parseInt(gpuMatch[1]) : 8;
        const tp = tpMatch ? parseInt(tpMatch[1]) : 8;

        // POST each row as a benchmark run
        let stored = 0;
        for (const row of rows) {
            const payload = {
                model_name: modelId || 'unknown',
                gpu_platform: gpuPlatform,
                gpu_count: gpuCount,
                framework: cfg.framework || 'vllm',
                tp: tp,
                weight_dtype: cfg.weightDtype || 'bf16',
                throughput_tps: row.throughput_tps,
                ttft_p50: row.ttft_p50,
                ttft_p99: row.ttft_p99,
                tpot_p50: row.tpot_p50,
                itl_p50: row.itl_p50,
                max_num_seqs: row.max_num_seqs || null,
                chunked_prefill: row.chunked_prefill != null ? row.chunked_prefill : 0,
                evidence_source: 'benchmark_serving',
                conversation_id: State.currentConvId || null,
            };
            API.post('/benchmark-runs', payload).then(() => {
                stored++;
                if (stored === rows.length) {
                    this._showToast(stored + ' BENCHMARK RUN(S) STORED');
                    this.loadBenchmarks();
                }
            }).catch(e => console.warn('Failed to store benchmark run:', e));
        }
    },

    _tryParseGpuFromChat() {
        const msgs = document.querySelectorAll('.era-chat-messages .msg.assistant');
        if (!msgs.length) return;
        const lastMsg = msgs[msgs.length - 1]?.textContent || '';
        // Match patterns like "8x MI300X" or "8× AMD Instinct MI300X" or "Confirmed: 8x MI300X"
        const match = lastMsg.match(/(\d+)\s*[x×]\s*(?:AMD\s+Instinct\s+)?(MI\d+\w*)/i);
        if (!match) return;
        const gpuCount = parseInt(match[1]);
        const gpuModel = match[2].toUpperCase();
        // Match HBM like "192 GB HBM" or "192GB"
        const hbmMatch = lastMsg.match(/(\d+)\s*GB\s*(?:HBM|per\s*GPU)/i);
        const hbm = hbmMatch ? parseFloat(hbmMatch[1]) : 0;
        this._autoUpsertFleetNode({
            gpu_model: gpuModel,
            gpu_count: gpuCount,
            hbm_per_gpu_gb: hbm,
        });
    },

    _autoUpsertFleetNode(data) {
        if (!data.gpu_model && !data.gpu_count) return;
        const raw = localStorage.getItem('inferforge_era_config');
        if (!raw) return;
        try {
            const cfg = JSON.parse(raw);
            const headIp = cfg.head;
            if (!headIp) return;
            API.post('/fleet/nodes/upsert', {
                hostname: headIp,
                ip_address: headIp,
                ssh_user: cfg.user || null,
                gpu_platform: data.gpu_model || null,
                gpu_count: data.gpu_count || 0,
                hbm_per_gpu_gb: data.hbm_per_gpu_gb || 0,
                status: 'online',
            }).then(() => this.loadFleet()).catch(() => {});
        } catch (_) {}
    },

    _setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    },
};


/* ============================================================
   BOOT
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => Era.init());
