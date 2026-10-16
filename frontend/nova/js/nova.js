/* InferForge Nova -- DevOps Dashboard Controller
   ================================================= */

const Nova = {

    /* ---- Private state ---- */
    _ws: null,
    _wizStep: 1,
    _chatExpanded: false,
    _activeTab: 'wizard',

    /* ============================================================
       INITIALIZATION
       ============================================================ */

    async init() {
        MD.init();

        await Promise.all([
            this.loadStatus(),
            this.loadFleetNodes(),
        ]);

        try {
            const state = await API.get('/inference-state');
            if (state && (state.gpu_model || state.gpu_count)) {
                this._updateGpuBadge(state);
            }
        } catch (_) { /* no state yet */ }

        this._restoreWizardConfig();
        this._initTabs();
        this._initFrameworkPicker();
        this._initKeyboard();

        this.navigateTab('wizard');
    },


    /* ============================================================
       STATUS & API
       ============================================================ */

    async loadStatus() {
        try {
            const s = await API.get('/status');
            State.set('lastApiStatus', s);
            State.set('apiReady', !!s.api_connected);

            const dot = document.getElementById('nova-status-dot');
            const text = document.getElementById('nova-status-text');
            if (dot) dot.className = 'nova-status-indicator' + (State.apiReady ? '' : ' error');
            if (text) text.textContent = State.apiReady ? 'Ready' : 'Disconnected';
        } catch (e) {
            console.error('[Nova] Status error:', e);
            State.set('apiReady', false);
        }
    },

    _updateGpuBadge(data) {
        const badge = document.getElementById('nova-gpu-badge');
        if (!badge) return;
        const model = data.gpu_model || data.platform || '';
        const count = data.gpu_count || data.gpuCount || '';
        if (model && count) {
            badge.textContent = count + 'x ' + model;
        } else if (model) {
            badge.textContent = model;
        }
    },


    /* ============================================================
       TAB NAVIGATION
       ============================================================ */

    _initTabs() {
        document.querySelectorAll('.nova-tab[data-tab]').forEach(btn => {
            btn.addEventListener('click', () => {
                this.navigateTab(btn.dataset.tab);
            });
        });
    },

    navigateTab(tab) {
        this._activeTab = tab;

        document.querySelectorAll('.nova-tab').forEach(t => t.classList.remove('active'));
        const btn = document.querySelector(`.nova-tab[data-tab="${tab}"]`);
        if (btn) btn.classList.add('active');

        document.querySelectorAll('.nova-tab-panel').forEach(p => p.classList.remove('active'));
        const panel = document.getElementById('panel-' + tab);
        if (panel) {
            panel.classList.add('active');
            panel.style.animation = 'none';
            panel.offsetHeight; // reflow
            panel.style.animation = '';
        }

        if (tab === 'sessions') this._loadSessions();
        if (tab === 'campaigns') this._loadCampaigns();
        if (tab === 'recipes') this._loadRecipes();
        if (tab === 'deployments') this._loadDeployments();
    },


    /* ============================================================
       FLEET CARDS
       ============================================================ */

    async loadFleetNodes() {
        try {
            const data = await API.get('/fleet/nodes');
            const nodes = data.nodes || data || [];
            this._renderFleetCards(nodes);
        } catch (_) {
            // Fleet API may not be populated yet
        }
    },

    _renderFleetCards(nodes) {
        const container = document.getElementById('nova-fleet-scroll');
        const placeholder = document.getElementById('nova-fleet-placeholder');
        if (!container) return;

        if (!nodes || nodes.length === 0) {
            if (placeholder) placeholder.style.display = 'flex';
            return;
        }

        if (placeholder) placeholder.style.display = 'none';

        // Remove existing cards (keep placeholder)
        container.querySelectorAll('.nova-fleet-card').forEach(c => c.remove());

        for (const node of nodes) {
            const card = document.createElement('div');
            card.className = 'nova-fleet-card';

            const ip = node.ip || node.hostname || node.address || 'Unknown';
            const gpu = node.gpu_model || node.gpu || '---';
            const count = node.gpu_count || '?';
            const hbm = node.hbm_per_gpu || node.hbm || '---';
            const status = node.status || 'online';
            const util = node.utilization || 0;

            let barClass = '';
            if (util > 90) barClass = ' crit';
            else if (util > 70) barClass = ' warn';

            card.innerHTML = [
                '<div class="nova-fleet-card-header">',
                '  <span class="nova-fleet-card-ip">' + _esc(ip) + '</span>',
                '  <span class="nova-fleet-card-dot ' + _esc(status) + '"></span>',
                '</div>',
                '<div class="nova-fleet-card-meta">',
                '  <strong>' + _esc(String(count)) + 'x</strong> ' + _esc(gpu) +
                   (hbm !== '---' ? ' / ' + _esc(String(hbm)) + ' GB HBM' : ''),
                '</div>',
                '<div class="nova-fleet-bar-track">',
                '  <div class="nova-fleet-bar-fill' + barClass + '" style="width:' + Math.min(util, 100) + '%"></div>',
                '</div>',
            ].join('');

            container.appendChild(card);
        }
    },


    /* ============================================================
       WIZARD STATE MACHINE
       ============================================================ */

    wizNext() {
        if (this._wizStep >= 5) return;

        // Validate current step
        if (!this._validateWizStep(this._wizStep)) return;

        // If moving to step 5 (review), build the review table
        if (this._wizStep === 4) this._buildReviewTable();

        this._wizStep++;
        this._renderWizStep();
    },

    wizPrev() {
        if (this._wizStep <= 1) return;
        this._wizStep--;
        this._renderWizStep();
    },

    _renderWizStep() {
        const step = this._wizStep;

        // Update step indicators
        document.querySelectorAll('.nova-step').forEach(s => {
            const n = parseInt(s.dataset.step);
            s.classList.remove('active', 'completed');
            if (n === step) s.classList.add('active');
            else if (n < step) s.classList.add('completed');
        });

        // Update step lines
        const lines = document.querySelectorAll('.nova-step-line');
        lines.forEach((line, i) => {
            line.classList.toggle('completed', i < step - 1);
        });

        // Show active step content
        document.querySelectorAll('.nova-wizard-step').forEach(s => s.classList.remove('active'));
        const target = document.getElementById('wiz-step-' + step);
        if (target) target.classList.add('active');

        // Update nav buttons
        const backBtn = document.getElementById('nova-wiz-back');
        const nextBtn = document.getElementById('nova-wiz-next');
        if (backBtn) backBtn.disabled = step === 1;
        if (nextBtn) {
            nextBtn.textContent = step === 4 ? 'Review' : 'Next';
            nextBtn.style.display = step === 5 ? 'none' : '';
        }
    },

    _validateWizStep(step) {
        switch (step) {
            case 1: {
                const model = document.getElementById('wiz-model')?.value || '';
                if (!model) {
                    this._showToast('Select a model to continue.', 'warning');
                    return false;
                }
                if (model === 'custom') {
                    const cid = (document.getElementById('wiz-custom-id')?.value || '').trim();
                    if (!cid) {
                        this._showToast('Enter a HuggingFace model ID.', 'warning');
                        return false;
                    }
                }
                return true;
            }
            case 2:
                return true; // Framework always has a default
            case 3: {
                const head = (document.getElementById('wiz-head')?.value || '').trim();
                if (!head) {
                    this._showToast('Enter a head node IP to continue.', 'warning');
                    return false;
                }
                return true;
            }
            case 4:
                return true; // SLA targets are optional
            default:
                return true;
        }
    },

    onWizModelChange() {
        const val = document.getElementById('wiz-model')?.value || '';
        const wrap = document.getElementById('wiz-custom-wrap');
        if (wrap) {
            wrap.classList.toggle('hidden', val !== 'custom');
        }
    },

    _buildReviewTable() {
        const container = document.getElementById('nova-review-table');
        if (!container) return;

        const cfg = this._getWizardConfig();
        const rows = [
            ['Model', cfg.modelId || '---'],
            ['Weight Dtype', cfg.dtype.toUpperCase()],
            ['KV Dtype', cfg.kvDtype ? cfg.kvDtype.toUpperCase() : 'Same as weight'],
            ['Sequence Length', String(cfg.seqLen)],
            ['Framework', cfg.framework.toUpperCase()],
            ['Head Node', cfg.head || '---'],
            ['Workers', cfg.workers || 'None'],
            ['SSH User', cfg.user || 'root'],
            ['SSH Key', cfg.key || '~/.ssh/id_ed25519'],
            ['Model Path', cfg.modelPath || '---'],
            ['Run Type', cfg.runType === 'real' ? 'Real Run' : 'Simulation'],
            ['Execution Mode', cfg.execMode],
        ];

        // Add SLA targets if set
        if (cfg.slaTtft) rows.push(['Max TTFT', cfg.slaTtft + ' ms']);
        if (cfg.slaTpot) rows.push(['Max TPOT', cfg.slaTpot + ' ms']);
        if (cfg.slaThroughput) rows.push(['Min Throughput', cfg.slaThroughput + ' tok/s']);
        if (cfg.slaE2e) rows.push(['Max E2E Latency', cfg.slaE2e + ' ms']);

        container.innerHTML = rows.map(([k, v]) => [
            '<div class="nova-review-row">',
            '  <span class="nova-review-key">' + _esc(k) + '</span>',
            '  <span class="nova-review-val">' + _esc(v) + '</span>',
            '</div>',
        ].join('')).join('');
    },

    _getWizardConfig() {
        let modelId = document.getElementById('wiz-model')?.value || '';
        if (modelId === 'custom') {
            modelId = (document.getElementById('wiz-custom-id')?.value || '').trim();
        }

        const fw = document.querySelector('input[name="wiz-framework"]:checked');

        return {
            modelId,
            dtype:          document.getElementById('wiz-dtype')?.value || 'bf16',
            kvDtype:        document.getElementById('wiz-kv-dtype')?.value || '',
            seqLen:         parseInt(document.getElementById('wiz-seq-len')?.value || '4096', 10),
            framework:      fw ? fw.value : 'vllm',
            head:           (document.getElementById('wiz-head')?.value || '').trim(),
            workers:        (document.getElementById('wiz-workers')?.value || '').trim(),
            user:           (document.getElementById('wiz-user')?.value || 'root').trim(),
            key:            (document.getElementById('wiz-key')?.value || '~/.ssh/id_ed25519').trim(),
            modelPath:      (document.getElementById('wiz-model-path')?.value || '').trim(),
            runType:        document.getElementById('wiz-runtype')?.value || 'simulation',
            execMode:       document.getElementById('wiz-exec-mode')?.value || 'autonomous',
            slaTtft:        (document.getElementById('wiz-sla-ttft')?.value || '').trim(),
            slaTpot:        (document.getElementById('wiz-sla-tpot')?.value || '').trim(),
            slaThroughput:  (document.getElementById('wiz-sla-throughput')?.value || '').trim(),
            slaE2e:         (document.getElementById('wiz-sla-e2e')?.value || '').trim(),
        };
    },

    _restoreWizardConfig() {
        State.loadNodeConfig();
        const nc = State.nodeConfig;
        if (nc.head)       this._setVal('wiz-head', nc.head);
        if (nc.workers)    this._setVal('wiz-workers', nc.workers);
        if (nc.user)       this._setVal('wiz-user', nc.user);
        if (nc.key)        this._setVal('wiz-key', nc.key);
        if (nc.model_path) this._setVal('wiz-model-path', nc.model_path);
    },


    /* ============================================================
       LAUNCH FROM WIZARD
       ============================================================ */

    async launchFromWizard() {
        if (!State.apiReady) {
            this._showToast('API not connected.', 'error');
            return;
        }

        const cfg = this._getWizardConfig();

        // Save node config
        State.nodeConfig = {
            head: cfg.head,
            workers: cfg.workers,
            user: cfg.user,
            key: cfg.key,
            model_path: cfg.modelPath,
        };
        State.saveNodeConfig();
        API.post('/save-config', State.nodeConfig).catch(() => {});

        // Build the prompt
        const modePrefix = cfg.runType === 'simulation'
            ? '[MODE: SIMULATION -- memory analysis only. Do NOT launch Docker, do NOT download anything. Only allowed: SSH for GPU detection + run memory_calculator.py + present the 8-section report.]\n\n'
            : '[MODE: REAL RUN -- execute actual inference on the cluster.' +
              (cfg.modelPath ? ' Model path: ' + cfg.modelPath + '.' : ' Search for model weights before launching.') +
              ' If weights not found, ABORT with download instructions.]\n\n';

        const allNodes = cfg.workers ? cfg.head + ', ' + cfg.workers : cfg.head;

        let slaInfo = '';
        if (cfg.slaTtft || cfg.slaTpot || cfg.slaThroughput || cfg.slaE2e) {
            const parts = [];
            if (cfg.slaTtft) parts.push('TTFT < ' + cfg.slaTtft + 'ms');
            if (cfg.slaTpot) parts.push('TPOT < ' + cfg.slaTpot + 'ms');
            if (cfg.slaThroughput) parts.push('throughput > ' + cfg.slaThroughput + ' tok/s');
            if (cfg.slaE2e) parts.push('E2E < ' + cfg.slaE2e + 'ms');
            slaInfo = '\nSLA targets: ' + parts.join(', ') + '.';
        }

        const prompt = modePrefix +
            'Full auto-optimize pipeline for ' + cfg.modelId +
            ', dtype: ' + cfg.dtype +
            (cfg.kvDtype ? ', kv_dtype: ' + cfg.kvDtype : '') +
            ', seq_len: ' + cfg.seqLen +
            ', framework: ' + cfg.framework +
            '. SSH user ' + cfg.user +
            ', key ' + cfg.key +
            ', nodes: ' + allNodes + '.' +
            slaInfo;

        // Expand chat and send
        this.expandChat();
        this._sendToChat(prompt, cfg.framework === 'vllm' ? 'inference-optimize' : '', cfg.execMode);
    },


    /* ============================================================
       FRAMEWORK PICKER
       ============================================================ */

    _initFrameworkPicker() {
        document.querySelectorAll('.nova-framework-card').forEach(card => {
            card.addEventListener('click', () => {
                document.querySelectorAll('.nova-framework-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                const radio = card.querySelector('input[type="radio"]');
                if (radio) radio.checked = true;
            });
        });
    },


    /* ============================================================
       CHAT SLIDE-OUT
       ============================================================ */

    toggleChat() {
        if (this._chatExpanded) {
            this.collapseChat();
        } else {
            this.expandChat();
        }
    },

    expandChat() {
        const panel = document.getElementById('nova-chat-panel');
        const icon = document.getElementById('nova-chat-toggle-icon');
        if (panel) panel.classList.add('expanded');
        if (icon) icon.innerHTML = '&#9660;'; // down arrow
        this._chatExpanded = true;

        // Scroll to bottom
        const msgs = document.getElementById('nova-chat-messages');
        if (msgs) {
            requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
        }
    },

    collapseChat() {
        const panel = document.getElementById('nova-chat-panel');
        const icon = document.getElementById('nova-chat-toggle-icon');
        if (panel) panel.classList.remove('expanded');
        if (icon) icon.innerHTML = '&#9650;'; // up arrow
        this._chatExpanded = false;
    },


    /* ============================================================
       CHAT MESSAGING (WebSocket)
       ============================================================ */

    sendMessage() {
        const input = document.getElementById('nova-chat-input');
        const text = (input?.value || '').trim();
        if (!text || State.isGenerating) return;
        if (!State.apiReady) {
            this._showToast('API not connected.', 'error');
            return;
        }

        const skill = document.getElementById('nova-sel-skill')?.value || '';
        const mode = document.getElementById('nova-sel-mode')?.value || 'autonomous';

        this.expandChat();
        this._sendToChat(text, skill, mode);
        if (input) {
            input.value = '';
            this.autoResize(input);
        }
    },

    async _sendToChat(text, skill, mode) {
        // Create conversation if needed
        if (!State.currentConvId) {
            try {
                const data = await API.post('/conversations', {
                    title: text.slice(0, 60),
                    skill: skill || '',
                    mode: mode || 'autonomous',
                });
                State.set('currentConvId', data.id);
            } catch (e) {
                this._showToast('Failed to create conversation.', 'error');
                return;
            }
        }

        // Connect WS if not connected
        if (!this._ws || this._ws.readyState !== WebSocket.OPEN ||
            this._ws._cid !== State.currentConvId) {
            this._connectWebSocket(State.currentConvId);
        }

        // Add user bubble
        this._addChatBubble('user', text);
        this._setBusy();

        // Wait for WS to be ready
        const ws = this._ws;
        const waitForOpen = () => new Promise((resolve, reject) => {
            if (ws && ws.readyState === WebSocket.OPEN) return resolve();
            const check = setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN) { clearInterval(check); resolve(); }
            }, 50);
            setTimeout(() => { clearInterval(check); reject(new Error('WS timeout')); }, 5000);
        });

        try {
            await waitForOpen();
            ws.send(JSON.stringify({
                type: 'message',
                content: text,
                skill: skill || '',
                mode: mode || 'autonomous',
                run_type: 'simulation', // default
            }));
        } catch (e) {
            this._showToast('WebSocket connection failed.', 'error');
            this._setIdle();
        }
    },

    _connectWebSocket(cid) {
        if (this._ws) {
            this._ws.onmessage = null;
            this._ws.onclose = null;
            this._ws.close();
            this._ws = null;
        }

        this._ws = API.connectWebSocket('/ws/chat/' + cid, {
            onOpen: () => {},
            onClose: () => { this._setIdle(); },
            onError: () => { this._setIdle(); },
            onMessage: (data) => this._handleEvent(data),
        });
        this._ws._cid = cid;
    },

    _handleEvent(ev) {
        switch (ev.type) {
            case 'connected':
                if (ev.job_running) this._setBusy();
                break;

            case 'replay_start':
                break;

            case 'replay_end':
                // Reload messages for clean state
                if (State.currentConvId) {
                    API.get('/conversations/' + State.currentConvId).then(data => {
                        this._clearChatMessages();
                        for (const msg of (data.messages || [])) {
                            if (msg.role === 'user') this._addChatBubble('user', msg.content);
                            else if (msg.role === 'assistant') this._addChatBubble('assistant', msg.content);
                        }
                    });
                }
                break;

            case 'text_delta':
                if (!this._currentMsgEl) this._startAssistantBubble();
                this._appendToCurrentMsg(ev.content);
                break;

            case 'tool_use_start':
                if (!this._currentMsgEl) this._startAssistantBubble();
                this._addToolIndicator(ev.tool_name);
                break;

            case 'tool_output_line':
                // Silently consume tool output in Nova
                break;

            case 'tool_use_end':
                break;

            case 'message_complete':
                this._finalizeCurrentMsg();
                this._setIdle();
                break;

            case 'error':
                if (this._currentMsgEl) {
                    this._appendToCurrentMsg('\n\n**Error:** ' + ev.content);
                    this._finalizeCurrentMsg();
                } else {
                    this._addChatBubble('assistant', '**Error:** ' + ev.content);
                }
                this._setIdle();
                break;

            case 'inference_update':
            case 'inference_state_update':
                if (ev.data) {
                    this._updateGpuBadge(ev.data);
                    this.loadFleetNodes();
                }
                break;
        }
    },


    /* ============================================================
       CHAT DOM HELPERS
       ============================================================ */

    /** @type {HTMLElement|null} */
    _currentMsgEl: null,

    _chatContainer() {
        return document.getElementById('nova-chat-messages');
    },

    _clearChatMessages() {
        const c = this._chatContainer();
        if (c) c.innerHTML = '';
        this._currentMsgEl = null;
    },

    _addChatBubble(role, text) {
        const c = this._chatContainer();
        if (!c) return;
        const div = document.createElement('div');
        div.className = 'msg ' + role;
        if (role === 'assistant') {
            div.innerHTML = [
                '<div class="msg-header">',
                '  <div class="msg-avatar" style="background:var(--nova-accent);">IF</div>',
                '  <span class="msg-name">InferForge</span>',
                '</div>',
                '<div class="msg-content">' + MD.render(text) + '</div>',
            ].join('');
        } else {
            div.textContent = text;
        }
        c.appendChild(div);
        this._scrollChatBottom();
    },

    _startAssistantBubble() {
        const c = this._chatContainer();
        if (!c) return;
        const div = document.createElement('div');
        div.className = 'msg assistant';
        div.innerHTML = [
            '<div class="msg-header">',
            '  <div class="msg-avatar" style="background:var(--nova-accent);">IF</div>',
            '  <span class="msg-name">InferForge</span>',
            '  <span class="running-badge">Running...</span>',
            '</div>',
            '<div class="msg-content"></div>',
        ].join('');
        c.appendChild(div);
        this._currentMsgEl = div;
        this._scrollChatBottom();
    },

    _appendToCurrentMsg(text) {
        if (!this._currentMsgEl) return;
        const content = this._currentMsgEl.querySelector('.msg-content');
        if (!content) return;
        if (!content.dataset.raw) content.dataset.raw = '';
        content.dataset.raw += text;
        content.innerHTML = MD.render(content.dataset.raw);
        this._scrollChatBottom();
    },

    _addToolIndicator(toolName) {
        if (!this._currentMsgEl) return;
        const content = this._currentMsgEl.querySelector('.msg-content');
        if (!content) return;
        if (!content.dataset.raw) content.dataset.raw = '';
        // Append a subtle tool-use note
        content.dataset.raw += '\n`[tool: ' + toolName + ']`\n';
        content.innerHTML = MD.render(content.dataset.raw);
        this._scrollChatBottom();
    },

    _finalizeCurrentMsg() {
        if (!this._currentMsgEl) return;
        const badge = this._currentMsgEl.querySelector('.running-badge');
        if (badge) badge.remove();
        const content = this._currentMsgEl.querySelector('.msg-content');
        if (content && content.dataset.raw) {
            content.innerHTML = MD.render(content.dataset.raw);
        }
        this._currentMsgEl = null;
        this._scrollChatBottom();
    },

    _scrollChatBottom() {
        const c = this._chatContainer();
        if (c) requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; });
    },


    /* ============================================================
       JOB CONTROL
       ============================================================ */

    stopJob() {
        if (!State.currentConvId) return;
        this._addChatBubble('assistant', '**Job stopped by user.** Results above may be incomplete.');
        this._setIdle();
        API.post('/cancel/' + State.currentConvId).catch(() => {});
    },

    _setBusy() {
        State.set('isGenerating', true);
        const sendBtn = document.getElementById('nova-btn-send');
        const stopBtn = document.getElementById('nova-btn-stop');
        const badge = document.getElementById('nova-chat-badge');
        const dot = document.getElementById('nova-status-dot');

        if (sendBtn) sendBtn.disabled = true;
        if (stopBtn) stopBtn.classList.add('visible');
        if (badge) { badge.textContent = 'Running'; badge.className = 'nova-chat-badge running'; }
        if (dot) dot.className = 'nova-status-indicator busy';
    },

    _setIdle() {
        State.set('isGenerating', false);
        const sendBtn = document.getElementById('nova-btn-send');
        const stopBtn = document.getElementById('nova-btn-stop');
        const badge = document.getElementById('nova-chat-badge');
        const dot = document.getElementById('nova-status-dot');

        if (sendBtn) sendBtn.disabled = !State.apiReady;
        if (stopBtn) stopBtn.classList.remove('visible');
        if (badge) { badge.textContent = ''; badge.className = 'nova-chat-badge'; }
        if (dot) dot.className = 'nova-status-indicator' + (State.apiReady ? '' : ' error');

        document.querySelectorAll('.running-badge').forEach(b => b.remove());
    },


    /* ============================================================
       DATA LOADING (Sessions, Campaigns, Recipes, Deployments)
       ============================================================ */

    async _loadSessions() {
        try {
            const data = await API.get('/hyperloom-sessions');
            const sessions = data.sessions || data || [];
            const container = document.getElementById('nova-sessions-list');
            if (!container) return;
            if (!sessions.length) return;

            const table = this._buildDataTable(
                ['ID', 'Model', 'Framework', 'Status', 'Created'],
                sessions.map(s => [
                    s.id?.slice(0, 8) || '---',
                    s.model || '---',
                    s.framework || '---',
                    s.status || 'unknown',
                    s.created_at ? new Date(s.created_at).toLocaleDateString() : '---',
                ])
            );
            container.innerHTML = '';
            container.appendChild(table);
        } catch (_) {}
    },

    async _loadCampaigns() {
        try {
            const data = await API.get('/campaigns');
            const campaigns = data.campaigns || data || [];
            const container = document.getElementById('nova-campaigns-list');
            if (!container || !campaigns.length) return;

            const table = this._buildDataTable(
                ['ID', 'Name', 'Status', 'Runs', 'Created'],
                campaigns.map(c => [
                    c.id?.slice(0, 8) || '---',
                    c.name || '---',
                    c.status || 'pending',
                    String(c.runs_count || 0),
                    c.created_at ? new Date(c.created_at).toLocaleDateString() : '---',
                ])
            );
            container.innerHTML = '';
            container.appendChild(table);
        } catch (_) {}
    },

    async _loadRecipes() {
        try {
            const data = await API.get('/recipes');
            const recipes = data.recipes || data || [];
            const container = document.getElementById('nova-recipes-list');
            if (!container || !recipes.length) return;

            const table = this._buildDataTable(
                ['Name', 'Model', 'Framework', 'TP', 'Dtype'],
                recipes.map(r => [
                    r.name || '---',
                    r.model || '---',
                    r.framework || '---',
                    String(r.tp || '---'),
                    r.dtype || '---',
                ])
            );
            container.innerHTML = '';
            container.appendChild(table);
        } catch (_) {}
    },

    async _loadDeployments() {
        try {
            const data = await API.get('/deployments');
            const deploys = data.deployments || data || [];
            const container = document.getElementById('nova-deployments-list');
            if (!container || !deploys.length) return;

            const table = this._buildDataTable(
                ['ID', 'Model', 'Node', 'Status', 'Created'],
                deploys.map(d => [
                    d.id?.slice(0, 8) || '---',
                    d.model || '---',
                    d.node || '---',
                    d.status || 'unknown',
                    d.created_at ? new Date(d.created_at).toLocaleDateString() : '---',
                ])
            );
            container.innerHTML = '';
            container.appendChild(table);
        } catch (_) {}
    },

    _buildDataTable(headers, rows) {
        const table = document.createElement('table');
        table.className = 'data-table striped';

        const thead = document.createElement('thead');
        thead.innerHTML = '<tr>' + headers.map(h => '<th>' + _esc(h) + '</th>').join('') + '</tr>';
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        for (const row of rows) {
            const tr = document.createElement('tr');
            tr.innerHTML = row.map(cell => '<td>' + _esc(cell) + '</td>').join('');
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);

        return table;
    },


    /* ============================================================
       PLACEHOLDER ACTIONS
       ============================================================ */

    importSession() {
        this._showToast('Session import coming soon', 'info');
    },

    launchSession() {
        this.navigateTab('wizard');
    },

    createCampaign() {
        this.navigateTab('wizard');
        this._showToast('Configure a campaign from the Wizard', 'info');
    },

    syncRecipes() {
        this._showToast('Recipe sync coming soon', 'info');
    },


    /* ============================================================
       MAGIC COMMANDS (adapted for wizard context)
       ============================================================ */

    magicCmd(cmd) {
        if (!State.apiReady) return;

        const cfg = this._getWizardConfig();
        if (!cfg.head) {
            this._showToast('Configure cluster nodes in the Wizard first.', 'warning');
            return;
        }

        const allNodes = cfg.workers ? cfg.head + ', ' + cfg.workers : cfg.head;
        const modelDesc = cfg.modelId
            ? cfg.modelId + ', dtype: ' + cfg.dtype + ', seq_len: ' + cfg.seqLen
            : 'No model selected';

        const modePrefix = cfg.runType === 'simulation'
            ? '[MODE: SIMULATION]\n\n'
            : '[MODE: REAL RUN]\n\n';

        const commands = {
            'detect': modePrefix + 'Detect GPUs on ' + allNodes + '. SSH user ' + cfg.user + ', key ' + cfg.key + '.',
            'calculate': modePrefix + 'Memory analysis for ' + modelDesc + '. Head: ' + cfg.head + '.',
            'benchmark': modePrefix + cfg.framework + ' benchmark for ' + modelDesc + '. Nodes: ' + allNodes + '.',
        };

        const text = commands[cmd] || (modePrefix + cmd);
        this.expandChat();
        this._sendToChat(text, 'inference-optimize', cfg.execMode);
    },


    /* ============================================================
       KEYBOARD
       ============================================================ */

    _initKeyboard() {
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                this.sendMessage();
            }
            if (e.key === 'Escape') {
                if (State.isGenerating) {
                    this.stopJob();
                } else if (this._chatExpanded) {
                    this.collapseChat();
                }
            }
        });
    },

    handleChatKey(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            this.sendMessage();
        }
    },

    autoResize(el) {
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 100) + 'px';
    },


    /* ============================================================
       UTILITIES
       ============================================================ */

    _setVal(id, val) {
        const el = document.getElementById(id);
        if (el) el.value = val;
    },

    _showToast(message, type) {
        type = type || 'info';
        const toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        document.body.appendChild(toast);

        // Offset for Nova chat panel
        toast.style.bottom = '130px';
        toast.textContent = message;

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 400);
        }, 2500);
    },
};


/* ============================================================
   BOOT
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => Nova.init());
