/* InferForge -- Classic Theme Controller
   ========================================= */

const Classic = {

    /* ---- Private state ---- */
    _ws: null,
    _jobGen: 0,
    _prevConvId: null,
    _prevChatHTML: null,
    _inReplay: false,
    _replayJobWasRunning: false,

    /* ============================================================
       INITIALIZATION
       ============================================================ */

    async init() {
        // Initialize markdown renderer
        MD.init();

        // Load status + conversations in parallel
        await Promise.all([
            this.loadStatus(),
            this.loadConversations(),
        ]);

        // Load saved inference state
        try {
            const state = await API.get('/inference-state');
            if (state && (state.gpu_model || state.gpu_count)) {
                this.renderInferenceState({
                    detected: true,
                    platform: state.gpu_model || null,
                    gpuCount: state.gpu_count || null,
                    hbm: state.hbm_total || null,
                    last_benchmark: state.last_benchmark || null,
                });
            }
        } catch (_) { /* no state yet */ }

        // Restore node config
        this.restoreNodeConfig();

        // Attach navigation
        this.initNavigation();

        // Attach keyboard shortcuts
        this.initKeyboard();

        // Init chat scroll tracking
        Chat.initScrollTracking();

        // Navigate to home
        this.goHome();

        // Focus input
        const input = document.getElementById('chat-input');
        if (input) input.focus();
    },


    /* ============================================================
       STATUS & API
       ============================================================ */

    async loadStatus() {
        try {
            const s = await API.get('/status');
            State.set('lastApiStatus', s);
            State.set('apiReady', !!s.api_connected);

            const dot = document.getElementById('status-dot');
            const text = document.getElementById('status-text');
            if (dot) {
                dot.className = State.apiReady ? 'status-dot' : 'status-dot error';
                dot.title = State.apiReady ? 'Connected' : (s.api_connection_error || 'Not connected');
            }
            if (text) {
                text.textContent = State.apiReady ? 'Ready' : 'Disconnected';
            }
        } catch (e) {
            console.error('[Classic] Status error:', e);
            State.set('apiReady', false);
        }
    },


    /* ============================================================
       NAVIGATION
       ============================================================ */

    initNavigation() {
        document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
            btn.addEventListener('click', () => {
                const page = btn.dataset.page;
                this.navigateTo(page);
            });
        });
    },

    navigateTo(page) {
        // Update nav active state
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        const navBtn = document.querySelector(`.nav-item[data-page="${page}"]`);
        if (navBtn) navBtn.classList.add('active');

        // Hide all pages, show target
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const target = document.getElementById('page-' + page);
        if (target) {
            target.classList.add('active', 'entering');
            setTimeout(() => target.classList.remove('entering'), 250);
        }

        State.set('currentPage', page);

        // Update topbar title
        const titles = {
            home: 'InferForge',
            chat: State.currentConvId ? 'Chat' : 'New Chat',
            sessions: 'Hyperloom Sessions',
            campaigns: 'Campaigns',
            fleet: 'GPU Fleet',
            recipes: 'Recipe Browser',
            deployments: 'Deployments',
        };
        document.getElementById('topbar-title').textContent = titles[page] || 'InferForge';
    },

    goHome() {
        State.set('currentConvId', null);
        Chat.currentMsgEl = null;
        Chat.currentToolEl = null;
        State.set('isGenerating', false);
        this._hideBusyUI();
        this.navigateTo('home');
        this.loadConversations();
    },


    /* ============================================================
       CONVERSATIONS
       ============================================================ */

    async loadConversations() {
        try {
            const convs = await API.get('/conversations');
            const el = document.getElementById('conv-list');
            if (!el) return;
            el.innerHTML = '';

            if (!convs || !convs.length) {
                el.innerHTML = '<div style="padding:8px 10px;color:var(--text-dim);font-size:12px;">No conversations yet</div>';
                return;
            }

            const today = new Date().toDateString();
            const yesterday = new Date(Date.now() - 86400000).toDateString();
            let lastGroup = '';

            for (const c of convs) {
                const d = new Date(c.updated_at + 'Z').toDateString();
                let group = d === today ? 'Today' : d === yesterday ? 'Yesterday' : 'Older';
                if (group !== lastGroup) {
                    const groupEl = document.createElement('div');
                    groupEl.className = 'conv-group-title';
                    groupEl.textContent = group;
                    el.appendChild(groupEl);
                    lastGroup = group;
                }
                const active = c.id === State.currentConvId ? ' active' : '';
                const div = document.createElement('div');
                div.className = 'conv-item' + active;
                div.onclick = () => this.loadConversation(c.id);

                const badge = c.skill ? `<span class="conv-skill-badge">${_esc(c.skill)}</span>` : '';
                div.innerHTML = badge +
                    '<span class="conv-title">' + _esc(c.title) + '</span>' +
                    '<button class="conv-delete-btn" title="Delete">&times;</button>';

                const delBtn = div.querySelector('.conv-delete-btn');
                delBtn.onclick = (e) => { e.stopPropagation(); this.deleteConversation(c.id); };

                el.appendChild(div);
            }
        } catch (e) {
            console.error('[Classic] Failed to load conversations:', e);
        }
    },

    async loadConversation(cid) {
        // Switch to chat page
        this.navigateTo('chat');

        // If same conversation and WS still open, just restore
        if (cid === this._prevConvId && this._prevChatHTML &&
            this._ws && this._ws.readyState === WebSocket.OPEN && this._ws._cid === cid) {
            State.set('currentConvId', cid);
            const container = Chat.container();
            if (container) container.innerHTML = this._prevChatHTML;
            this._prevConvId = null;
            this._prevChatHTML = null;
            Chat.scrollToBottom(true);
            await this.loadConversations();
            return;
        }

        this._prevConvId = null;
        this._prevChatHTML = null;
        State.set('currentConvId', cid);

        const data = await API.get('/conversations/' + cid);
        Chat.clear();

        if (data.conversation) {
            document.getElementById('topbar-title').textContent = data.conversation.title || 'Chat';
            if (data.conversation.skill) {
                const sel = document.getElementById('sel-skill');
                if (sel) sel.value = data.conversation.skill;
            }
            if (data.conversation.mode) {
                const sel = document.getElementById('sel-mode');
                if (sel) sel.value = data.conversation.mode;
            }
        }

        for (const msg of data.messages || []) {
            if (msg.role === 'user') Chat.addUserBubble(msg.content);
            else if (msg.role === 'assistant') Chat.addAssistantBubble(msg.content, msg.tool_calls);
        }

        await this.loadConversations();
        this.connectWebSocket(cid);
        Chat.scrollToBottom(true);
    },

    async deleteConversation(cid) {
        if (!confirm('Delete this conversation?')) return;
        await API.del('/conversations/' + cid);
        if (State.currentConvId === cid || this._prevConvId === cid) {
            if (this._ws) { this._ws.onmessage = null; this._ws.close(); this._ws = null; }
            this._prevConvId = null;
            this._prevChatHTML = null;
            this.goHome();
        } else {
            await this.loadConversations();
        }
    },

    async newChat() {
        if (!State.apiReady) return;
        if (this._ws) { this._ws.onmessage = null; this._ws.close(); this._ws = null; }
        this._prevConvId = null;
        this._prevChatHTML = null;

        const skill = document.getElementById('sel-skill')?.value || '';
        const mode = document.getElementById('sel-mode')?.value || 'autonomous';
        const data = await API.post('/conversations', { title: 'New Conversation', skill, mode });
        State.set('currentConvId', data.id);
        Chat.clear();

        this.navigateTo('chat');
        document.getElementById('topbar-title').textContent = 'New Conversation';
        await this.loadConversations();
        this.connectWebSocket(data.id);
        document.getElementById('chat-input')?.focus();
    },


    /* ============================================================
       WEBSOCKET
       ============================================================ */

    connectWebSocket(cid) {
        if (this._ws && this._ws.readyState === WebSocket.OPEN && this._ws._cid === cid) return;
        if (this._ws) { this._ws.onmessage = null; this._ws.onclose = null; this._ws.close(); this._ws = null; }

        this._ws = API.connectWebSocket('/ws/chat/' + cid, {
            onOpen: () => {
                this.addActivity('Connected', 'ok');
            },
            onClose: () => {
                this.addActivity('Disconnected', 'error');
                this._setIdle();
            },
            onError: () => {
                this.addActivity('Connection error', 'error');
            },
            onMessage: (data) => this.handleEvent(data),
        });
        this._ws._cid = cid;
    },

    handleEvent(ev) {
        if (!State.currentConvId) return;

        switch (ev.type) {
            case 'connected':
                this._replayJobWasRunning = !!ev.job_running;
                if (ev.job_running) {
                    this.addActivity('Job resumed -- streaming live results', 'info');
                    this._setBusy();
                } else {
                    this.addActivity('Connected (no active job)', 'ok');
                    if (!State.isGenerating) this._setIdle();
                }
                break;

            case 'replay_start':
                this._inReplay = true;
                break;

            case 'replay_end':
                this._inReplay = false;
                if (!this._replayJobWasRunning) {
                    // Reload conversation from DB for clean state
                    Chat.finalizeCurrentMsg();
                    this._setIdle();
                    if (State.currentConvId) {
                        API.get('/conversations/' + State.currentConvId).then(data => {
                            Chat.clear();
                            if (data.conversation) {
                                document.getElementById('topbar-title').textContent = data.conversation.title || 'Chat';
                            }
                            for (const msg of (data.messages || [])) {
                                if (msg.role === 'user') Chat.addUserBubble(msg.content);
                                else if (msg.role === 'assistant') Chat.addAssistantBubble(msg.content, msg.tool_calls);
                            }
                            Chat.scrollToBottom(true);
                        });
                    }
                } else {
                    this.addActivity('Caught up -- streaming live', 'info');
                }
                break;

            case 'text_delta':
                if (!Chat.currentMsgEl) Chat.startAssistantBubble();
                Chat.appendToCurrentMsg(ev.content);
                break;

            case 'tool_use_start':
                // Collapse previous tool block
                if (Chat.currentToolEl) {
                    const prevToggle = Chat.currentToolEl.querySelector('.tool-toggle');
                    const prevBody = Chat.currentToolEl.querySelector('.tool-body');
                    if (prevToggle) prevToggle.classList.remove('open');
                    if (prevBody) prevBody.classList.remove('visible');
                }
                if (!Chat.currentMsgEl) Chat.startAssistantBubble();
                Chat.addToolBlock(Chat.currentMsgEl, ev.tool_name, ev.input);
                if (!this._inReplay) {
                    this.addActivity('Tool: ' + ev.tool_name, 'tool');
                    const eo = document.getElementById('exec-output');
                    if (eo) eo.textContent = '$ ' + (ev.input?.command || ev.tool_name) + '\n';
                }
                break;

            case 'tool_output_line':
                Chat.appendToolOutput(Chat.currentToolEl, ev.content);
                if (!this._inReplay) {
                    const eo = document.getElementById('exec-output');
                    if (eo) { eo.textContent += ev.content; eo.scrollTop = eo.scrollHeight; }
                }
                break;

            case 'tool_use_end':
                Chat.finalizeToolBlock(Chat.currentToolEl, ev.exit_code);
                Chat.currentToolEl = null;
                if (!this._inReplay) {
                    const rc = ev.exit_code;
                    const isOk = rc === 0;
                    const isWarn = [255, 15, 143, 144, 1, 2].includes(rc);
                    const tag = isOk ? 'ok' : isWarn ? 'warn' : 'error';
                    this.addActivity('Exit: ' + rc + (isWarn ? ' (non-critical)' : ''), tag);
                }
                break;

            case 'message_complete':
                Chat.finalizeCurrentMsg();
                this._setIdle();
                this.loadConversations();
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
                    const d = ev.data;
                    this.renderInferenceState({
                        detected: !!(d.gpu_model || d.platform),
                        platform: d.gpu_model || d.platform || null,
                        gpuCount: d.gpu_count || d.gpuCount || null,
                        hbm: d.hbm_total || d.hbm || null,
                        last_benchmark: d.last_benchmark || null,
                    });
                }
                break;
        }
    },


    /* ============================================================
       SEND MESSAGE
       ============================================================ */

    sendMessage() {
        const input = document.getElementById('chat-input');
        const text = (input?.value || '').trim();
        if (!text || State.isGenerating) return;
        if (!State.apiReady) return;

        // If no conversation, create one first
        if (!State.currentConvId) {
            this._newChatThenSend(text);
            return;
        }

        // If WS disconnected, reconnect
        if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
            this.connectWebSocket(State.currentConvId);
            const _text = text;
            input.value = '';
            this.autoResize(input);
            Chat.addUserBubble(_text);
            this._setBusy();
            const check = setInterval(() => {
                if (this._ws && this._ws.readyState === WebSocket.OPEN) {
                    clearInterval(check);
                    this._ws.send(JSON.stringify({
                        type: 'message',
                        content: _text,
                        skill: document.getElementById('sel-skill')?.value || '',
                        mode: document.getElementById('sel-mode')?.value || 'autonomous',
                        run_type: document.getElementById('sel-runtype')?.value || 'simulation',
                    }));
                }
            }, 50);
            return;
        }

        Chat.addUserBubble(text);
        input.value = '';
        this.autoResize(input);
        this._setBusy();

        this._ws.send(JSON.stringify({
            type: 'message',
            content: text,
            skill: document.getElementById('sel-skill')?.value || '',
            mode: document.getElementById('sel-mode')?.value || 'autonomous',
            run_type: document.getElementById('sel-runtype')?.value || 'simulation',
        }));
        this.addActivity('Message sent', 'info');
        Chat.scrollToBottom(true);
    },

    async _newChatThenSend(text) {
        if (!State.apiReady) return;
        if (this._ws) { this._ws.onmessage = null; this._ws.onclose = null; this._ws.close(); this._ws = null; }

        const skill = document.getElementById('sel-skill')?.value || '';
        const mode = document.getElementById('sel-mode')?.value || 'autonomous';
        const data = await API.post('/conversations', { title: text.slice(0, 60), skill, mode });
        State.set('currentConvId', data.id);
        Chat.clear();

        this.navigateTo('chat');
        document.getElementById('topbar-title').textContent = text.slice(0, 60);

        this.connectWebSocket(data.id);

        // Wait for WS open
        await new Promise((resolve, reject) => {
            const check = setInterval(() => {
                if (this._ws && this._ws.readyState === WebSocket.OPEN) { clearInterval(check); resolve(); }
            }, 50);
            setTimeout(() => { clearInterval(check); reject(new Error('WebSocket timeout')); }, 5000);
        });

        Chat.addUserBubble(text);
        document.getElementById('chat-input').value = '';
        this._setBusy();
        this._ws.send(JSON.stringify({ type: 'message', content: text, skill, mode }));
        this.addActivity('Message sent', 'info');
        await this.loadConversations();
    },


    /* ============================================================
       MAGIC COMMANDS (Quick Actions)
       ============================================================ */

    magicCmd(cmd) {
        if (!State.apiReady) return;
        this.saveNodeConfig();

        const nc = State.nodeConfig;
        const h = nc.head || '';
        const w = nc.workers || '';
        const u = nc.user || 'root';
        const k = nc.key || '~/.ssh/id_rsa';
        const mp = nc.model_path || '';

        if (!h) return; // Need at least head node

        const runType = document.getElementById('sel-runtype')?.value || 'simulation';
        const allNodes = w ? h + ', ' + w : h;
        const ms = this.getModelSelection();
        const modelDesc = ms.modelId
            ? 'Model: ' + ms.modelId + ', dtype: ' + ms.dtype + ', seq_len: ' + ms.seqLen + ', framework: ' + ms.framework
            : 'No model selected';

        const modePrefix = runType === 'simulation'
            ? '[MODE: SIMULATION -- memory analysis only. Do NOT launch Docker, do NOT download anything. Only allowed: SSH for GPU detection + run memory_calculator.py + present the 8-section report.]\n\n'
            : '[MODE: REAL RUN -- execute actual inference on the cluster.' +
              (mp ? ' Model path: ' + mp + '.' : ' Search for model weights before launching.') +
              ' If weights not found, ABORT with download instructions.]\n\n';

        const commands = {
            'detect': modePrefix + 'Detect GPU platform on cluster nodes (' + allNodes + '). SSH user ' + u + ', key ' + k + '.',
            'calculate': modePrefix + 'Memory analysis for ' + modelDesc + '. SSH user ' + u + ', key ' + k + ', head ' + h + '.',
            'benchmark-vllm': modePrefix + 'vLLM benchmark for ' + modelDesc + '. SSH user ' + u + ', key ' + k + ', head ' + h + '.',
            'benchmark-sglang': modePrefix + 'SGLang benchmark for ' + modelDesc + '. SSH user ' + u + ', key ' + k + ', head ' + h + '.',
            'hyperloom': modePrefix + 'Run Hyperloom kernel optimization for ' + modelDesc + '. SSH user ' + u + ', key ' + k + ', head ' + h + '.',
            'campaign': modePrefix + 'Run multi-framework comparison campaign for ' + modelDesc + '. SSH user ' + u + ', key ' + k + ', head ' + h + '.',
            'auto-optimize': modePrefix + 'Full auto-optimize pipeline for ' + modelDesc + '. SSH user ' + u + ', key ' + k + ', head ' + h + '.',
            'deploy': modePrefix + 'Deploy best configuration for ' + modelDesc + '. SSH user ' + u + ', key ' + k + ', head ' + h + '.',
        };

        const text = commands[cmd] || (modePrefix + 'Run ' + cmd + ' on ' + h);

        // Switch to chat and send
        this.navigateTo('chat');
        const input = document.getElementById('chat-input');
        if (input) input.value = text;
        this.sendMessage();
    },


    /* ============================================================
       NODE CONFIG
       ============================================================ */

    saveNodeConfig() {
        State.nodeConfig = {
            head:       (document.getElementById('cfg-head')?.value || '').trim(),
            workers:    (document.getElementById('cfg-workers')?.value || '').trim(),
            user:       (document.getElementById('cfg-user')?.value || 'root').trim(),
            key:        (document.getElementById('cfg-key')?.value || '~/.ssh/id_rsa').trim(),
            model_path: (document.getElementById('cfg-model-path')?.value || '').trim(),
        };
        State.saveNodeConfig();

        // Persist to backend
        API.post('/save-config', State.nodeConfig).catch(() => {});

        // Button feedback
        const btn = document.getElementById('cfg-save-btn');
        if (btn) {
            btn.textContent = 'Saved';
            btn.style.background = 'var(--green)';
            setTimeout(() => { btn.textContent = 'Save Config'; btn.style.background = ''; }, 2000);
        }

        this._showToast('Cluster config saved', 'success');
        this.updateFrameworkStat();
    },

    restoreNodeConfig() {
        State.loadNodeConfig();
        const nc = State.nodeConfig;
        if (nc.head)       this._setVal('cfg-head', nc.head);
        if (nc.workers)    this._setVal('cfg-workers', nc.workers);
        if (nc.user)       this._setVal('cfg-user', nc.user);
        if (nc.key)        this._setVal('cfg-key', nc.key);
        if (nc.model_path) this._setVal('cfg-model-path', nc.model_path);
    },

    importNodes() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.txt,.csv,.json';
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const text = await file.text();
            let ips = [];
            try {
                const parsed = JSON.parse(text);
                if (Array.isArray(parsed)) ips = parsed;
                else if (parsed.nodes) ips = Object.keys(parsed.nodes);
                else if (parsed.node_dict) ips = Object.keys(parsed.node_dict);
            } catch (_) {
                ips = text.split(/[\n,]+/).map(s => s.trim()).filter(s => /^\d/.test(s));
            }
            if (ips.length > 0) {
                this._setVal('cfg-head', ips[0]);
                this._setVal('cfg-workers', ips.slice(1).join(', '));
                this.saveNodeConfig();
                this._showToast('Imported ' + ips.length + ' nodes', 'success');
            } else {
                this._showToast('No valid IPs found in file', 'warning');
            }
        };
        input.click();
    },

    probeCluster() {
        this.saveNodeConfig();
        this.magicCmd('detect');
    },


    /* ============================================================
       MODEL SELECTION
       ============================================================ */

    onModelChange() {
        const sel = document.getElementById('cfg-model');
        const wrap = document.getElementById('cfg-custom-wrap');
        if (wrap) wrap.style.display = sel?.value === 'custom' ? '' : 'none';
    },

    getModelSelection() {
        const modelSel = document.getElementById('cfg-model');
        let modelId = modelSel ? modelSel.value : '';
        if (modelId === 'custom') {
            modelId = (document.getElementById('cfg-custom-id')?.value || '').trim();
        }
        return {
            modelId,
            dtype: document.getElementById('cfg-dtype')?.value || 'bf16',
            seqLen: parseInt(document.getElementById('cfg-seq-len')?.value || '4096', 10),
            framework: document.getElementById('cfg-framework')?.value || 'vllm',
        };
    },

    updateFrameworkStat() {
        const fw = document.getElementById('cfg-framework');
        const el = document.getElementById('stat-framework');
        if (fw && el) el.textContent = fw.value.toUpperCase() || '\u2014';
    },


    /* ============================================================
       INFERENCE STATE RENDERING
       ============================================================ */

    renderInferenceState(data) {
        if (!data || !data.detected) return;

        State.updateInferenceState(data);

        if (data.platform) {
            this._setText('stat-gpu-model', data.platform);
        }
        if (data.gpuCount) {
            this._setText('stat-gpu-count', data.gpuCount);
        }
        if (data.hbm) {
            this._setText('stat-hbm-total', data.hbm);
        }
        if (data.last_benchmark) {
            const el = document.getElementById('stat-benchmark');
            if (el) {
                el.textContent = data.last_benchmark;
                el.style.fontSize = '12px';
            }
        }
    },


    /* ============================================================
       ACTIVITY LOG
       ============================================================ */

    addActivity(text, tag = 'info') {
        const log = document.getElementById('activity-log');
        if (!log) return;

        const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const icons = {
            ok:    '<svg viewBox="0 0 16 16" fill="#00c896" width="12" height="12"><circle cx="8" cy="8" r="4"/></svg>',
            error: '<svg viewBox="0 0 16 16" fill="#ff4466" width="12" height="12"><circle cx="8" cy="8" r="4"/></svg>',
            warn:  '<svg viewBox="0 0 16 16" fill="#ffaa00" width="12" height="12"><circle cx="8" cy="8" r="4"/></svg>',
            info:  '<svg viewBox="0 0 16 16" fill="#4488ff" width="12" height="12"><circle cx="8" cy="8" r="4"/></svg>',
            tool:  '<svg viewBox="0 0 16 16" fill="#8866ff" width="12" height="12"><circle cx="8" cy="8" r="4"/></svg>',
        };

        const item = document.createElement('div');
        item.className = 'activity-item';
        item.innerHTML =
            '<span class="activity-time">' + now + '</span>' +
            '<span class="activity-icon">' + (icons[tag] || icons.info) + '</span>' +
            '<span class="activity-text">' + _esc(text) + '</span>';
        log.prepend(item);
    },


    /* ============================================================
       JOB CONTROL
       ============================================================ */

    stopJob() {
        if (!State.currentConvId) return;
        this.addActivity('Stop requested', 'warn');

        const container = Chat.container();
        if (container) {
            const notice = document.createElement('div');
            notice.className = 'msg assistant';
            notice.style.cssText = 'border-color: var(--red); background: var(--red-dim);';
            notice.innerHTML = '<strong>Job stopped by user</strong> -- results above may be incomplete.';
            container.appendChild(notice);
            Chat.scrollToBottom(true);
        }

        this._setIdle();
        API.post('/cancel/' + State.currentConvId).catch(() => {});
    },

    _setBusy() {
        State.set('isGenerating', true);
        const sendBtn = document.getElementById('btn-send');
        const stopBtn = document.getElementById('btn-stop');
        if (sendBtn) sendBtn.disabled = true;
        if (stopBtn) stopBtn.classList.add('visible');

        const dot = document.getElementById('status-dot');
        if (dot) dot.className = 'status-dot busy';

        // Show topbar badge
        const title = document.getElementById('topbar-title');
        if (title && !title.querySelector('.topbar-status')) {
            const badge = document.createElement('span');
            badge.className = 'topbar-status running';
            badge.textContent = 'Running...';
            title.appendChild(badge);
        }

        Chat.showThinking();
    },

    _setIdle() {
        State.set('isGenerating', false);
        const sendBtn = document.getElementById('btn-send');
        const stopBtn = document.getElementById('btn-stop');
        const input = document.getElementById('chat-input');
        if (sendBtn) sendBtn.disabled = !State.apiReady;
        if (stopBtn) stopBtn.classList.remove('visible');
        if (input) input.disabled = false;

        const dot = document.getElementById('status-dot');
        if (dot) dot.className = State.apiReady ? 'status-dot' : 'status-dot error';

        Chat.hideThinking();
        document.querySelectorAll('.running-badge').forEach(b => b.remove());

        const title = document.getElementById('topbar-title');
        const badge = title?.querySelector('.topbar-status');
        if (badge) {
            badge.className = 'topbar-status done';
            badge.textContent = 'Done';
            setTimeout(() => badge.remove(), 4000);
        }
    },

    _hideBusyUI() {
        const stopBtn = document.getElementById('btn-stop');
        if (stopBtn) stopBtn.classList.remove('visible');
        Chat.hideThinking();
        document.querySelectorAll('.running-badge').forEach(b => b.remove());
        const badge = document.querySelector('.topbar-status');
        if (badge) badge.remove();
    },


    /* ============================================================
       RIGHT PANEL
       ============================================================ */

    toggleRightPanel() {
        document.getElementById('right-panel')?.classList.toggle('collapsed');
    },


    /* ============================================================
       PLACEHOLDER ACTIONS (pages not yet implemented)
       ============================================================ */

    importSession() {
        this._showToast('Session import coming soon', 'info');
    },

    launchSession() {
        this.magicCmd('hyperloom');
    },

    createCampaign() {
        this.magicCmd('campaign');
    },

    addNode() {
        this.navigateTo('home');
        document.getElementById('cfg-head')?.focus();
    },

    syncRecipes() {
        this._showToast('Recipe sync coming soon', 'info');
    },


    /* ============================================================
       KEYBOARD
       ============================================================ */

    initKeyboard() {
        document.addEventListener('keydown', (e) => {
            // Ctrl+Enter = send from anywhere
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                this.sendMessage();
            }
            // Escape = cancel generation or go home
            if (e.key === 'Escape') {
                if (State.isGenerating) {
                    this.stopJob();
                } else if (State.currentPage !== 'home') {
                    this.goHome();
                }
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
        el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    },


    /* ============================================================
       UTILITIES
       ============================================================ */

    _setVal(id, val) {
        const el = document.getElementById(id);
        if (el) el.value = val;
    },

    _setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    },

    _showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 400);
        }, 2500);
    },
};

/* ============================================================
   BOOT
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => Classic.init());
