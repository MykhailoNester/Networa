/* Shared Chart.js configuration.
 *
 * Chart.js is vendored at /static/vendor/chart.min.js and loaded before this
 * file. Every chart in the app is built through these helpers rather than
 * configured inline, so hovering behaves identically everywhere: the whole x
 * position responds (the cursor never has to land exactly on a marker), each
 * record is drawn as a visible point, and tooltips read money out in the
 * active display currency instead of as a bare number.
 */
(function (window) {
    'use strict';

    var GRID_COLOR = '#2a2a2a';
    var TICK_COLOR = '#888';

    /* Hover anywhere along a date and every series reports its value there. */
    var INTERACTION = { mode: 'index', intersect: false, axis: 'x' };

    /* One marker per record, thinned as the series grows so a long history
       stays readable. Never 0: "which dates do I actually have?" is the
       question the markers exist to answer. */
    function pointRadius(count) {
        if (count > 240) return 1;
        if (count > 90) return 1.5;
        if (count > 40) return 2.5;
        return 3.5;
    }

    function money(symbol, value, decimals) {
        var d = (decimals === undefined || decimals === null) ? 0 : decimals;
        var n = Number(value);
        if (!isFinite(n)) return symbol + '0';
        return symbol + n.toLocaleString(undefined, {
            minimumFractionDigits: d,
            maximumFractionDigits: d
        });
    }

    /* The dark-theme tooltip box. Pass a Chart.js label callback to control the
       text; omit it to keep Chart.js's default. */
    function tooltip(labelFn) {
        var cfg = {
            backgroundColor: '#1e1e2e',
            borderColor: '#333',
            borderWidth: 1,
            titleColor: '#ccc',
            bodyColor: '#aaa',
            padding: 10
        };
        if (labelFn) cfg.callbacks = { label: labelFn };
        return cfg;
    }

    /* "<series>: $1,234" for any cartesian chart. */
    function moneyTooltip(symbol, decimals) {
        return tooltip(function (ctx) {
            var name = (ctx.dataset && ctx.dataset.label) ? ctx.dataset.label + ': ' : '';
            return ' ' + name + money(symbol, ctx.parsed.y, decimals);
        });
    }

    function moneyScales(symbol) {
        return {
            x: {
                grid: { color: GRID_COLOR },
                ticks: { color: TICK_COLOR, maxTicksLimit: 8 }
            },
            y: {
                grid: { color: GRID_COLOR },
                ticks: {
                    color: TICK_COLOR,
                    callback: function (v) { return money(symbol, v); }
                }
            }
        };
    }

    /* A line series with its markers already sized for the record count.
       `data` is whatever the chart plots — convert to the display currency
       before calling, not after. */
    function lineDataset(cfg) {
        var color = cfg.color || '#6366f1';
        return {
            label: cfg.label,
            data: cfg.data,
            borderColor: color,
            backgroundColor: cfg.fill ? (cfg.fillColor || color) : 'transparent',
            borderDash: cfg.dashed ? [5, 5] : undefined,
            fill: !!cfg.fill,
            tension: 0.3,
            pointRadius: pointRadius(cfg.data.length),
            pointHoverRadius: 6,
            pointBackgroundColor: color,
            pointBorderColor: color,
            pointHoverBackgroundColor: color,
            pointHoverBorderColor: '#fff',
            pointHoverBorderWidth: 2,
            /* Generous hit box: reading a value should not require pixel aim. */
            pointHitRadius: 12
        };
    }

    window.NetworaCharts = {
        INTERACTION: INTERACTION,
        pointRadius: pointRadius,
        money: money,
        tooltip: tooltip,
        moneyTooltip: moneyTooltip,
        moneyScales: moneyScales,
        lineDataset: lineDataset
    };
})(window);
