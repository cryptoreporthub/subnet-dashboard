/* uPlot sparklines for premium cockpit indicators */
(function () {
  'use strict';

  var sparkPlots = new WeakMap();

  function parseSpark(raw) {
    if (!raw) return null;
    var pts = raw.split(',').map(Number).filter(function (n) { return !isNaN(n); });
    return pts.length >= 2 ? pts : null;
  }

  function destroySpark(el) {
    var plot = sparkPlots.get(el);
    if (plot) {
      plot.destroy();
      sparkPlots.delete(el);
    }
  }

  function drawSpark(el) {
    if (typeof uPlot === 'undefined') return;
    var pts = parseSpark(el.getAttribute('data-spark'));
    if (!pts) return;
    destroySpark(el);
    var up = pts[pts.length - 1] >= pts[0];
    var col = up ? '#34d399' : '#f43f5e';
    var xs = pts.map(function (_, i) { return i; });
    var w = el.clientWidth || 96;
    var h = el.clientHeight || 36;
    var plot = new uPlot({
      width: w,
      height: h,
      pxAlign: 1,
      cursor: { show: false },
      legend: { show: false },
      scales: { x: { show: false }, y: { show: false } },
      axes: [],
      series: [
        {},
        {
          stroke: col,
          width: 1.6,
          fill: up ? 'rgba(52,211,153,0.25)' : 'rgba(244,63,94,0.25)',
        },
      ],
    }, [xs, pts], el);
    sparkPlots.set(el, plot);
  }

  function paintSparks() {
    document.querySelectorAll('.spark[data-spark]').forEach(drawSpark);
  }

  window.__paintSparks = paintSparks;
})();
