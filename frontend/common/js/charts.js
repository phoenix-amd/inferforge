/* InferForge -- Lightweight Canvas Charts
   ========================================== */

const Charts = {

    /* ---- Color helpers ---- */
    _colors: {
        green:  '#00c896',
        blue:   '#4488ff',
        cyan:   '#00d4ff',
        amber:  '#ffaa00',
        red:    '#ff4466',
        purple: '#8866ff',
        text:   '#e0e0f0',
        muted:  '#8888aa',
        dim:    '#555577',
        grid:   '#2a2a44',
        bg:     '#0a0a14',
    },

    /**
     * Attach scroll-to-zoom and double-click-to-reset to a canvas.
     * Only attaches once per canvas (checks for data-zoom-attached).
     */
    _attachZoom(canvas) {
        if (canvas.dataset.zoomAttached) return;
        canvas.dataset.zoomAttached = '1';
        canvas.dataset.zoomScale = '1';
        canvas.style.cursor = 'zoom-in';
        canvas.style.transformOrigin = 'top left';
        canvas.style.transition = 'transform 0.15s ease';

        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY < 0 ? 1.15 : 1 / 1.15;
            let scale = parseFloat(canvas.dataset.zoomScale) * delta;
            scale = Math.min(Math.max(scale, 0.5), 5);
            canvas.dataset.zoomScale = scale;
            canvas.style.transform = `scale(${scale})`;
            canvas.style.cursor = scale > 1 ? 'zoom-out' : 'zoom-in';
        }, { passive: false });

        canvas.addEventListener('dblclick', () => {
            canvas.dataset.zoomScale = '1';
            canvas.style.transform = 'scale(1)';
            canvas.style.cursor = 'zoom-in';
        });
    },

    /**
     * Get canvas 2D context and set up for HiDPI.
     */
    _setup(canvas, width, height) {
        const dpr = window.devicePixelRatio || 1;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        return { ctx, w: width, h: height };
    },

    /**
     * Draw a bar chart.
     * @param {HTMLCanvasElement} canvas
     * @param {Array<{label: string, value: number, color?: string}>} data
     * @param {Object} opts - { title?, maxValue?, height?, barWidth?, showLabels? }
     */
    drawBarChart(canvas, data, opts = {}) {
        const w = canvas.parentElement?.clientWidth || 400;
        const h = opts.height || 200;
        const { ctx } = this._setup(canvas, w, h);
        const C = this._colors;

        const pad = { top: 30, right: 20, bottom: 70, left: 50 };
        const plotW = w - pad.left - pad.right;
        const plotH = h - pad.top - pad.bottom;
        const maxVal = opts.maxValue || Math.max(...data.map(d => d.value), 1);
        const barW = opts.barWidth || Math.min(32, (plotW / data.length) * 0.6);
        const gap = (plotW - barW * data.length) / (data.length + 1);

        // Background
        ctx.fillStyle = C.bg;
        ctx.fillRect(0, 0, w, h);

        // Title
        if (opts.title) {
            ctx.fillStyle = C.muted;
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(opts.title.toUpperCase(), pad.left, 18);
        }

        // Grid lines
        ctx.strokeStyle = C.grid;
        ctx.lineWidth = 0.5;
        const gridLines = 4;
        for (let i = 0; i <= gridLines; i++) {
            const y = pad.top + (plotH / gridLines) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();

            // Y-axis labels
            const val = maxVal - (maxVal / gridLines) * i;
            ctx.fillStyle = C.dim;
            ctx.font = '10px JetBrains Mono, monospace';
            ctx.textAlign = 'right';
            ctx.fillText(val.toFixed(0), pad.left - 8, y + 4);
        }

        // Bars
        data.forEach((d, i) => {
            const x = pad.left + gap + i * (barW + gap);
            const barH = (d.value / maxVal) * plotH;
            const y = pad.top + plotH - barH;
            const color = d.color || C.blue;

            // Bar fill
            const grad = ctx.createLinearGradient(x, y, x, y + barH);
            grad.addColorStop(0, color);
            grad.addColorStop(1, color + '60');
            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.roundRect(x, y, barW, barH, [3, 3, 0, 0]);
            ctx.fill();

            // Value on top
            if (opts.showLabels !== false) {
                ctx.fillStyle = color;
                ctx.font = '10px JetBrains Mono, monospace';
                ctx.textAlign = 'center';
                ctx.fillText(d.value.toFixed(0), x + barW / 2, y - 6);
            }

            // X-axis label — rotated 45°
            const lx = x + barW / 2;
            const ly = pad.top + plotH + 8;
            ctx.save();
            ctx.translate(lx, ly);
            ctx.rotate(Math.PI / 4);
            ctx.fillStyle = C.muted;
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(d.label || '', 0, 0);
            ctx.restore();
        });
        this._attachZoom(canvas);
    },

    /**
     * Draw a line chart.
     * @param {HTMLCanvasElement} canvas
     * @param {Array<{label: string, value: number}>} data
     * @param {Object} opts - { title?, color?, height?, fill?, showDots? }
     */
    drawLineChart(canvas, data, opts = {}) {
        const w = canvas.parentElement?.clientWidth || 400;
        const h = opts.height || 200;
        const { ctx } = this._setup(canvas, w, h);
        const C = this._colors;

        const pad = { top: 30, right: 20, bottom: 70, left: 50 };
        const plotW = w - pad.left - pad.right;
        const plotH = h - pad.top - pad.bottom;
        const maxVal = Math.max(...data.map(d => d.value), 1) * 1.1;
        const minVal = Math.min(...data.map(d => d.value), 0);
        const range = maxVal - minVal || 1;
        const color = opts.color || C.cyan;

        // Background
        ctx.fillStyle = C.bg;
        ctx.fillRect(0, 0, w, h);

        // Title
        if (opts.title) {
            ctx.fillStyle = C.muted;
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(opts.title.toUpperCase(), pad.left, 18);
        }

        // Grid
        ctx.strokeStyle = C.grid;
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 4; i++) {
            const y = pad.top + (plotH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
            const val = maxVal - (range / 4) * i;
            ctx.fillStyle = C.dim;
            ctx.font = '10px JetBrains Mono, monospace';
            ctx.textAlign = 'right';
            ctx.fillText(val.toFixed(1), pad.left - 8, y + 4);
        }

        if (data.length < 2) return;

        // Build points
        const points = data.map((d, i) => ({
            x: pad.left + (plotW / (data.length - 1)) * i,
            y: pad.top + plotH - ((d.value - minVal) / range) * plotH,
        }));

        // Fill area
        if (opts.fill !== false) {
            ctx.beginPath();
            ctx.moveTo(points[0].x, pad.top + plotH);
            points.forEach(p => ctx.lineTo(p.x, p.y));
            ctx.lineTo(points[points.length - 1].x, pad.top + plotH);
            ctx.closePath();
            const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
            grad.addColorStop(0, color + '30');
            grad.addColorStop(1, color + '05');
            ctx.fillStyle = grad;
            ctx.fill();
        }

        // Line
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        points.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
        ctx.stroke();

        // Dots
        if (opts.showDots !== false) {
            points.forEach(p => {
                ctx.beginPath();
                ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();
                ctx.strokeStyle = C.bg;
                ctx.lineWidth = 1.5;
                ctx.stroke();
            });
        }

        // X labels — rotated 45°
        const step = Math.max(1, Math.floor(data.length / 6));
        data.forEach((d, i) => {
            if (i % step !== 0 && i !== data.length - 1) return;
            const lx = points[i].x;
            const ly = pad.top + plotH + 8;
            ctx.save();
            ctx.translate(lx, ly);
            ctx.rotate(Math.PI / 4);
            ctx.fillStyle = C.muted;
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(d.label || '', 0, 0);
            ctx.restore();
        });
        this._attachZoom(canvas);
    },

    /**
     * Draw a gauge/ring chart (HBM utilization, etc).
     * @param {HTMLCanvasElement} canvas
     * @param {number} value - Current value
     * @param {number} max   - Maximum value
     * @param {Object} opts  - { title?, size?, color?, unit?, label? }
     */
    drawGaugeChart(canvas, value, max, opts = {}) {
        const size = opts.size || 120;
        const { ctx } = this._setup(canvas, size, size);
        const C = this._colors;

        const cx = size / 2;
        const cy = size / 2;
        const radius = (size - 20) / 2;
        const lineW = 8;
        const pct = Math.min(value / (max || 1), 1);

        // Pick color based on percentage
        let color;
        if (opts.color) {
            color = opts.color;
        } else if (pct >= 0.9) {
            color = C.red;
        } else if (pct >= 0.7) {
            color = C.amber;
        } else {
            color = C.green;
        }

        // Background ring
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = C.grid;
        ctx.lineWidth = lineW;
        ctx.stroke();

        // Value arc
        const startAngle = -Math.PI / 2;
        const endAngle = startAngle + pct * Math.PI * 2;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, endAngle);
        ctx.strokeStyle = color;
        ctx.lineWidth = lineW;
        ctx.lineCap = 'round';
        ctx.stroke();

        // Center text -- percentage
        ctx.fillStyle = color;
        ctx.font = 'bold 18px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(Math.round(pct * 100) + '%', cx, cy - 6);

        // Label below
        if (opts.label) {
            ctx.fillStyle = C.muted;
            ctx.font = '10px Inter, sans-serif';
            ctx.fillText(opts.label, cx, cy + 14);
        }

        // Value + unit
        if (opts.unit) {
            ctx.fillStyle = C.dim;
            ctx.font = '9px JetBrains Mono, monospace';
            ctx.fillText(value.toFixed(1) + ' / ' + max.toFixed(0) + ' ' + opts.unit, cx, cy + 28);
        }
    },

    /**
     * Draw a Gantt-style timeline chart.
     * @param {HTMLCanvasElement} canvas
     * @param {Array<{label: string, start: number, end: number, color?: string, status?: string}>} events
     * @param {Object} opts - { title?, height?, rowHeight? }
     */
    drawGanttChart(canvas, events, opts = {}) {
        if (!events.length) return;

        const rowH = opts.rowHeight || 28;
        const w = canvas.parentElement?.clientWidth || 600;
        const h = opts.height || Math.max(100, events.length * rowH + 60);
        const { ctx } = this._setup(canvas, w, h);
        const C = this._colors;

        const pad = { top: 30, right: 20, bottom: 20, left: 140 };
        const plotW = w - pad.left - pad.right;

        const tMin = Math.min(...events.map(e => e.start));
        const tMax = Math.max(...events.map(e => e.end));
        const tRange = tMax - tMin || 1;

        // Background
        ctx.fillStyle = C.bg;
        ctx.fillRect(0, 0, w, h);

        // Title
        if (opts.title) {
            ctx.fillStyle = C.muted;
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(opts.title.toUpperCase(), pad.left, 18);
        }

        const statusColors = {
            running:   C.amber,
            complete:  C.green,
            error:     C.red,
            pending:   C.dim,
        };

        events.forEach((ev, i) => {
            const y = pad.top + i * rowH;
            const x1 = pad.left + ((ev.start - tMin) / tRange) * plotW;
            const x2 = pad.left + ((ev.end - tMin) / tRange) * plotW;
            const barW = Math.max(x2 - x1, 4);
            const color = ev.color || statusColors[ev.status] || C.blue;

            // Row label
            ctx.fillStyle = C.muted;
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            ctx.fillText(ev.label, pad.left - 10, y + rowH / 2);

            // Row line
            ctx.strokeStyle = C.grid;
            ctx.lineWidth = 0.5;
            ctx.beginPath();
            ctx.moveTo(pad.left, y + rowH / 2);
            ctx.lineTo(w - pad.right, y + rowH / 2);
            ctx.stroke();

            // Bar
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.roundRect(x1, y + 4, barW, rowH - 8, 3);
            ctx.fill();

            // Duration text
            const dur = ev.end - ev.start;
            const durStr = dur >= 60 ? (dur / 60).toFixed(1) + 'm' : dur.toFixed(0) + 's';
            if (barW > 30) {
                ctx.fillStyle = '#000';
                ctx.font = '9px JetBrains Mono, monospace';
                ctx.textAlign = 'center';
                ctx.fillText(durStr, x1 + barW / 2, y + rowH / 2 + 1);
            }
        });
        this._attachZoom(canvas);
    },

    /**
     * Draw a multi-series line chart (e.g. util/temp/power over time).
     * @param {HTMLCanvasElement} canvas
     * @param {Array<{name: string, color: string, unit: string, data: number[]}>} series
     * @param {Array<string>} labels - X-axis labels (timestamps)
     * @param {Object} opts - { title?, height?, maxPoints? }
     */
    drawMultiLineChart(canvas, series, labels, opts = {}) {
        const w = canvas.parentElement?.clientWidth || 400;
        const h = opts.height || 160;
        const { ctx } = this._setup(canvas, w, h);
        const C = this._colors;

        const pad = { top: 26, right: 16, bottom: 28, left: 40 };
        const plotW = w - pad.left - pad.right;
        const plotH = h - pad.top - pad.bottom;

        // Background
        ctx.fillStyle = C.bg;
        ctx.fillRect(0, 0, w, h);

        // Title
        if (opts.title) {
            ctx.fillStyle = C.muted;
            ctx.font = '10px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(opts.title.toUpperCase(), pad.left, 14);
        }

        // Grid
        ctx.strokeStyle = C.grid;
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 4; i++) {
            const y = pad.top + (plotH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
        }

        if (!labels.length) return;

        // Draw each series
        for (const s of series) {
            const data = s.data;
            if (!data.length) continue;

            // Single point — draw a flat dashed line at that value
            if (data.length === 1) {
                const val = data[0] || 0;
                const maxVal = Math.max(val * 1.1, 1);
                const y = pad.top + plotH - (val / maxVal) * plotH;
                ctx.setLineDash([4, 4]);
                ctx.strokeStyle = s.color + '88';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(pad.left, y);
                ctx.lineTo(w - pad.right, y);
                ctx.stroke();
                ctx.setLineDash([]);
                continue;
            }

            const maxVal = Math.max(...data, 1) * 1.1;
            const minVal = Math.min(...data, 0);
            const range = maxVal - minVal || 1;

            const points = data.map((v, i) => ({
                x: pad.left + (plotW / (data.length - 1)) * i,
                y: pad.top + plotH - ((v - minVal) / range) * plotH,
            }));

            // Fill
            ctx.beginPath();
            ctx.moveTo(points[0].x, pad.top + plotH);
            points.forEach(p => ctx.lineTo(p.x, p.y));
            ctx.lineTo(points[points.length - 1].x, pad.top + plotH);
            ctx.closePath();
            ctx.fillStyle = s.color + '12';
            ctx.fill();

            // Line
            ctx.strokeStyle = s.color;
            ctx.lineWidth = 1.5;
            ctx.lineJoin = 'round';
            ctx.beginPath();
            points.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
            ctx.stroke();
        }

        // Inline legend (skip if hideLegend option set — use HTML legend instead)
        if (!opts.hideLegend) {
            let lx = w - pad.right;
            ctx.textAlign = 'right';
            ctx.font = '9px JetBrains Mono, monospace';
            for (let i = series.length - 1; i >= 0; i--) {
                const s = series[i];
                const lastVal = s.data[s.data.length - 1];
                const label = s.name + ': ' + (lastVal != null ? lastVal.toFixed(0) : '--') + (s.unit || '');
                const tw = ctx.measureText(label).width;
                ctx.fillStyle = s.color;
                ctx.fillText(label, lx, 14);
                lx -= tw + 14;
            }
        }

        // X labels
        const step = Math.max(1, Math.floor(labels.length / 5));
        ctx.fillStyle = C.dim;
        ctx.font = '9px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        labels.forEach((lbl, i) => {
            if (i % step !== 0 && i !== labels.length - 1) return;
            const x = pad.left + (plotW / (labels.length - 1)) * i;
            ctx.fillText(lbl, x, h - 6);
        });
        this._attachZoom(canvas);
    },
};

// Export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Charts;
}
