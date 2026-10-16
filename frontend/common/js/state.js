/* InferForge -- Global State Management
   ======================================== */

const State = {
    /* ---- Core state ---- */
    currentConvId: null,
    currentPage: 'home',       // home | chat | sessions | campaigns | fleet | recipes | deployments
    isGenerating: false,
    apiReady: false,
    lastApiStatus: null,

    /* ---- Node / Cluster config ---- */
    nodeConfig: JSON.parse(localStorage.getItem('inferforge_node_config') || '{}'),

    /* ---- Inference state (from backend) ---- */
    inferenceState: {},

    /* ---- Internal ---- */
    _listeners: {},

    /**
     * Update a state key and notify subscribers.
     * @param {string} key
     * @param {*} val
     */
    set(key, val) {
        const old = this[key];
        this[key] = val;
        this._notify(key, val, old);
    },

    /**
     * Subscribe to changes on a state key.
     * @param {string} key
     * @param {Function} callback - (newVal, oldVal) => void
     * @returns {Function} unsubscribe function
     */
    on(key, callback) {
        if (!this._listeners[key]) {
            this._listeners[key] = [];
        }
        this._listeners[key].push(callback);

        // Return unsubscribe function
        return () => {
            this._listeners[key] = this._listeners[key].filter(cb => cb !== callback);
        };
    },

    /**
     * Notify all listeners for a key.
     */
    _notify(key, newVal, oldVal) {
        const cbs = this._listeners[key] || [];
        for (const cb of cbs) {
            try {
                cb(newVal, oldVal);
            } catch (err) {
                console.error(`[State] Listener error for key "${key}":`, err);
            }
        }
    },

    /**
     * Persist node config to localStorage.
     */
    saveNodeConfig() {
        localStorage.setItem('inferforge_node_config', JSON.stringify(this.nodeConfig));
    },

    /**
     * Load node config from localStorage.
     */
    loadNodeConfig() {
        try {
            this.nodeConfig = JSON.parse(
                localStorage.getItem('inferforge_node_config') || '{}'
            );
        } catch (_) {
            this.nodeConfig = {};
        }
    },

    /**
     * Update the inference state (from backend WS events).
     * Merges data into existing state and notifies listeners.
     * @param {Object} data
     */
    updateInferenceState(data) {
        const old = { ...this.inferenceState };
        this.inferenceState = { ...this.inferenceState, ...data };
        this._notify('inferenceState', this.inferenceState, old);
    },

    /**
     * Save arbitrary key-value to localStorage under inferforge_ prefix.
     */
    persist(key, val) {
        localStorage.setItem('inferforge_' + key, JSON.stringify(val));
    },

    /**
     * Load arbitrary key from localStorage.
     */
    load(key, fallback = null) {
        try {
            const raw = localStorage.getItem('inferforge_' + key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (_) {
            return fallback;
        }
    },

    /**
     * Clear a persisted key.
     */
    forget(key) {
        localStorage.removeItem('inferforge_' + key);
    },
};

// Export for module systems (if present)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = State;
}
