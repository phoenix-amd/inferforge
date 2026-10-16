/* InferForge -- Chat Rendering Module
   ====================================== */

const Chat = {
    /** @type {HTMLElement|null} Current assistant message element being streamed */
    currentMsgEl: null,

    /** @type {HTMLElement|null} Current tool block element */
    currentToolEl: null,

    /**
     * Get the chat messages container element.
     * @returns {HTMLElement}
     */
    container() {
        return document.getElementById('chat-messages');
    },

    /**
     * Clear all messages from the chat area.
     */
    clear() {
        const c = this.container();
        if (c) c.innerHTML = '';
        this.currentMsgEl = null;
        this.currentToolEl = null;
    },

    /**
     * Add a user message bubble (right-aligned).
     * @param {string} text
     */
    addUserBubble(text) {
        const c = this.container();
        if (!c) return;
        const div = document.createElement('div');
        div.className = 'msg user';
        div.textContent = text;
        c.appendChild(div);
        this.scrollToBottom(true);
    },

    /**
     * Add a complete assistant message (for replaying history).
     * @param {string} text - Markdown text
     * @param {Array} toolCalls - Optional tool call records
     */
    addAssistantBubble(text, toolCalls) {
        const c = this.container();
        if (!c) return;
        const div = document.createElement('div');
        div.className = 'msg assistant';
        div.innerHTML = [
            '<div class="msg-header">',
            '  <div class="msg-avatar">IF</div>',
            '  <span class="msg-name">InferForge</span>',
            '</div>',
            '<div class="msg-content">' + MD.render(text) + '</div>',
        ].join('');
        if (toolCalls && toolCalls.length) {
            for (const tc of toolCalls) {
                this.addToolBlock(div, tc.tool, tc.input, true);
            }
        }
        c.appendChild(div);
        this.scrollToBottom(true);
    },

    /**
     * Start a new streaming assistant bubble and return the element reference.
     * @returns {HTMLElement}
     */
    startAssistantBubble() {
        const c = this.container();
        if (!c) return null;

        // Remove thinking indicator if present
        const thinking = c.querySelector('.thinking');
        if (thinking) thinking.remove();

        const div = document.createElement('div');
        div.className = 'msg assistant';
        div.innerHTML = [
            '<div class="msg-header">',
            '  <div class="msg-avatar">IF</div>',
            '  <span class="msg-name">InferForge</span>',
            '  <span class="running-badge">Running...</span>',
            '</div>',
            '<div class="msg-content"></div>',
        ].join('');
        c.appendChild(div);
        this.currentMsgEl = div;
        this.scrollToBottom(true);
        return div;
    },

    /**
     * Append HTML/text to the current streaming assistant message.
     * Accumulates raw markdown and re-renders.
     * @param {string} text
     */
    appendToCurrentMsg(text) {
        if (!this.currentMsgEl) return;
        const content = this.currentMsgEl.querySelector('.msg-content');
        if (!content) return;

        if (!content.dataset.raw) content.dataset.raw = '';
        content.dataset.raw += text;
        content.innerHTML = MD.render(content.dataset.raw);
        this.scrollToBottom();
    },

    /**
     * Finalize the current streaming message (remove running badge, final render).
     */
    finalizeCurrentMsg() {
        if (!this.currentMsgEl) return;
        const badge = this.currentMsgEl.querySelector('.running-badge');
        if (badge) badge.remove();
        const content = this.currentMsgEl.querySelector('.msg-content');
        if (content && content.dataset.raw) {
            content.innerHTML = MD.render(content.dataset.raw);
        }
        this.scrollToBottom(true);
        this.currentMsgEl = null;
        this.currentToolEl = null;
    },

    /**
     * Add a tool call block inside an assistant message.
     * @param {HTMLElement} parentEl - The assistant msg element (or null to use currentMsgEl)
     * @param {string} toolName
     * @param {Object} input
     * @param {boolean} collapsed - Start collapsed?
     * @returns {HTMLElement} The tool block element
     */
    addToolBlock(parentEl, toolName, input, collapsed = false) {
        const parent = parentEl || this.currentMsgEl;
        if (!parent) return null;

        const block = document.createElement('div');
        block.className = 'tool-block';

        const cmd = input?.command || input?.path || JSON.stringify(input || {});
        const shortCmd = cmd.length > 80 ? cmd.slice(0, 80) + '...' : cmd;

        block.innerHTML = [
            '<div class="tool-header" onclick="Chat.toggleToolBody(this)">',
            '  <span class="tool-icon">T</span>',
            '  <span class="tool-name">' + _esc(toolName) + '</span>',
            '  <span class="tool-hint">' + _esc(shortCmd) + '</span>',
            '  <span class="tool-status"></span>',
            '  <span class="tool-toggle ' + (collapsed ? '' : 'open') + '">&#9654;</span>',
            '</div>',
            '<div class="tool-body ' + (collapsed ? '' : 'visible') + '">',
            '  <div class="tool-cmd">$ ' + _esc(cmd) + '</div>',
            '  <div class="tool-output"></div>',
            '</div>',
        ].join('');

        parent.appendChild(block);
        this.currentToolEl = block;
        this.scrollToBottom();
        return block;
    },

    /**
     * Toggle a tool body's visibility (click handler).
     * @param {HTMLElement} headerEl
     */
    toggleToolBody(headerEl) {
        const toggle = headerEl.querySelector('.tool-toggle');
        const body = headerEl.nextElementSibling;
        if (toggle) toggle.classList.toggle('open');
        if (body) body.classList.toggle('visible');
    },

    /**
     * Append text to the current tool block's output.
     * @param {HTMLElement} toolEl
     * @param {string} text
     */
    appendToolOutput(toolEl, text) {
        const el = toolEl || this.currentToolEl;
        if (!el) return;
        const output = el.querySelector('.tool-output');
        if (output) {
            output.textContent += text;
            const body = el.querySelector('.tool-body');
            if (body) body.scrollTop = body.scrollHeight;
        }
    },

    /**
     * Finalize a tool block with exit code status.
     * @param {HTMLElement} toolEl
     * @param {number} exitCode
     */
    finalizeToolBlock(toolEl, exitCode) {
        const el = toolEl || this.currentToolEl;
        if (!el) return;
        const status = el.querySelector('.tool-status');
        if (status) {
            const isOk = exitCode === 0;
            const isWarn = [255, 15, 143, 144, 1, 2].includes(exitCode);
            if (isOk) {
                status.className = 'tool-status pass';
                status.textContent = 'exit 0';
            } else if (isWarn) {
                status.className = 'tool-status warn';
                status.textContent = 'exit ' + exitCode;
            } else {
                status.className = 'tool-status fail';
                status.textContent = 'exit ' + exitCode;
            }
        }
        // Collapse after completion
        const toggle = el.querySelector('.tool-toggle');
        const body = el.querySelector('.tool-body');
        if (toggle) toggle.classList.remove('open');
        if (body) body.classList.remove('visible');
    },

    /**
     * Show the thinking indicator.
     */
    showThinking() {
        const c = this.container();
        if (!c) return;
        // Remove existing
        const existing = c.querySelector('.thinking');
        if (existing) existing.remove();

        const div = document.createElement('div');
        div.className = 'thinking';
        div.innerHTML = [
            '<div class="thinking-dots">',
            '  <span></span><span></span><span></span>',
            '</div>',
            '<span>Thinking...</span>',
        ].join('');
        c.appendChild(div);
        this.scrollToBottom(true);
    },

    /**
     * Remove the thinking indicator.
     */
    hideThinking() {
        const c = this.container();
        if (!c) return;
        const thinking = c.querySelector('.thinking');
        if (thinking) thinking.remove();
    },

    /**
     * Scroll the chat container to bottom.
     * @param {boolean} force - Ignore user-scrolled-up state
     */
    scrollToBottom(force = false) {
        if (!force && this._userScrolledUp) return;
        const c = this.container();
        if (c) {
            requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; });
        }
    },

    /** @private Track if user manually scrolled up */
    _userScrolledUp: false,

    /**
     * Initialize scroll tracking on the chat container.
     */
    initScrollTracking() {
        const c = this.container();
        if (!c) return;
        c.addEventListener('scroll', () => {
            this._userScrolledUp =
                (c.scrollHeight - c.scrollTop - c.clientHeight) > 80;
        });
    },
};

/**
 * Escape HTML entities.
 * @param {string} s
 * @returns {string}
 */
function _esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

// Export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { Chat, _esc };
}
