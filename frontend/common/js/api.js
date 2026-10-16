/* InferForge -- Unified API Client
   =================================== */

const API = {
    base: '',
    token: null,

    /**
     * Core fetch wrapper with auth, JSON handling, and error normalization.
     */
    async fetch(path, opts = {}) {
        const url = this.base + '/api' + path;
        const headers = {
            'Content-Type': 'application/json',
            ...(opts.headers || {}),
        };
        if (this.token) {
            headers['Authorization'] = 'Bearer ' + this.token;
        }

        try {
            const resp = await fetch(url, {
                ...opts,
                headers,
            });

            if (!resp.ok) {
                let body = null;
                try { body = await resp.json(); } catch (_) {}
                let errDetail = body?.detail || body?.error || `HTTP ${resp.status}`;
                if (typeof errDetail === 'object') {
                    errDetail = errDetail.error || errDetail.message || errDetail.stderr || JSON.stringify(errDetail);
                }
                const err = new Error(errDetail);
                err.status = resp.status;
                err.body = body;
                throw err;
            }

            // 204 No Content
            if (resp.status === 204) return null;

            return await resp.json();
        } catch (err) {
            if (!err.status) {
                // Network error
                err.status = 0;
            }
            throw err;
        }
    },

    /** GET shorthand */
    async get(path) {
        return this.fetch(path);
    },

    /** POST shorthand */
    async post(path, body) {
        return this.fetch(path, {
            method: 'POST',
            body: body != null ? JSON.stringify(body) : undefined,
        });
    },

    /** PATCH shorthand */
    async patch(path, body) {
        return this.fetch(path, {
            method: 'PATCH',
            body: body != null ? JSON.stringify(body) : undefined,
        });
    },

    /** PUT shorthand */
    async put(path, body) {
        return this.fetch(path, {
            method: 'PUT',
            body: body != null ? JSON.stringify(body) : undefined,
        });
    },

    /** DELETE shorthand */
    async del(path) {
        return this.fetch(path, { method: 'DELETE' });
    },

    /**
     * Connect a WebSocket to the given path.
     * @param {string} path  - e.g. "/ws/chat/abc123"
     * @param {Object} handlers
     *   - onOpen(ws)
     *   - onMessage(data)  -- parsed JSON
     *   - onClose(event)
     *   - onError(event)
     * @returns {WebSocket}
     */
    connectWebSocket(path, handlers = {}) {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}${path}`;
        const ws = new WebSocket(url);

        ws.onopen = () => {
            if (handlers.onOpen) handlers.onOpen(ws);
        };

        ws.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (handlers.onMessage) handlers.onMessage(data);
            } catch (err) {
                console.error('[WS] Failed to parse message:', err);
            }
        };

        ws.onclose = (e) => {
            if (handlers.onClose) handlers.onClose(e);
        };

        ws.onerror = (e) => {
            if (handlers.onError) handlers.onError(e);
        };

        return ws;
    },
};

// Export for module systems (if present)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = API;
}
