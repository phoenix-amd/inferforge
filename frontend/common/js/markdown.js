/* InferForge -- Markdown Renderer
   ================================= */

const MD = {
    renderer: null,
    _ready: false,

    /**
     * Initialize the renderer. Uses markdown-it if loaded from CDN,
     * otherwise falls back to a basic regex-based renderer.
     */
    init() {
        if (typeof markdownit === 'function') {
            this.renderer = markdownit({
                html: false,
                linkify: true,
                breaks: true,
                typographer: false,
            });
            this._ready = true;
        } else {
            // Fallback -- basic regex renderer
            this.renderer = null;
            this._ready = true;
            console.warn('[MD] markdown-it not loaded, using fallback renderer');
        }
    },

    /**
     * Render markdown text to HTML.
     * @param {string} text - Markdown source
     * @returns {string} HTML output
     */
    render(text) {
        if (!this._ready) this.init();
        if (!text) return '';

        if (this.renderer) {
            return this.renderer.render(text);
        }

        return this._fallbackRender(text);
    },

    /**
     * Basic fallback renderer when markdown-it is not available.
     */
    _fallbackRender(s) {
        if (!s) return '';

        // Escape HTML
        s = s.replace(/&/g, '&amp;')
             .replace(/</g, '&lt;')
             .replace(/>/g, '&gt;');

        // Fenced code blocks
        s = s.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
            return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
        });

        // Inline code
        s = s.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Headers
        s = s.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        s = s.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        s = s.replace(/^# (.+)$/gm, '<h1>$1</h1>');

        // Bold / italic
        s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');

        // Tables
        s = s.replace(/^\|(.+)\|$/gm, row => {
            const cells = row.split('|').filter(c => c.trim());
            if (cells.every(c => /^[\s\-:]+$/.test(c))) return '';
            return '<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
        });
        s = s.replace(/(<tr>[\s\S]*?<\/tr>(\s*<tr>[\s\S]*?<\/tr>)*)/g,
            '<table>$1</table>');

        // Unordered lists
        s = s.replace(/^- (.+)$/gm, '<li>$1</li>');
        s = s.replace(/(<li>[\s\S]*?<\/li>(\s*<li>[\s\S]*?<\/li>)*)/g,
            '<ul>$1</ul>');

        // Links
        s = s.replace(/\[(.+?)\]\((.+?)\)/g,
            '<a href="$2" target="_blank" rel="noopener">$1</a>');

        // Paragraphs
        s = s.replace(/\n\n/g, '</p><p>');
        s = s.replace(/\n/g, '<br>');

        return '<p>' + s + '</p>';
    },
};

// Auto-init on load
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => MD.init());
    } else {
        MD.init();
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MD;
}
