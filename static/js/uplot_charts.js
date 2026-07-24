/* uPlot sparklines + canvas radar for premium cockpit (audit #10 completion) */
(function () {
  'use strict';

  var sparkPlots = new WeakMap();
  var radarResizeBound = false;

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
    var tone = el.getAttribute('data-spark-tone');
    var col;
    var fill;
    if (tone === 'warm') {
      col = '#fb923c';
      fill = 'rgba(251, 146, 60, 0.22)';
    } else if (tone === 'active') {
      col = '#34d399';
      fill = 'rgba(52, 211, 153, 0.25)';
    } else {
      col = up ? '#34d399' : '#f43f5e';
      fill = up ? 'rgba(52,211,153,0.25)' : 'rgba(244,63,94,0.25)';
    }
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
          fill: fill,
        },
      ],
    }, [xs, pts], el);
    sparkPlots.set(el, plot);
  }

  function paintSparks() {
    document.querySelectorAll('.spark[data-spark]').forEach(drawSpark);
  }

  function hexToRgba(hex, a) {
    var h = (hex || '').replace('#', '');
    if (h.length === 3) {
      h = h.split('').map(function (c) { return c + c; }).join('');
    }
    var n = parseInt(h, 16);
    if (isNaN(n)) return 'rgba(16,185,129,' + a + ')';
    var r = (n >> 16) & 255;
    var g = (n >> 8) & 255;
    var b = n & 255;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  function drawRadarCanvas(canvas) {
    var raw = canvas.getAttribute('data-radar');
    if (!raw) return;
    var radarData;
    try {
      radarData = JSON.parse(raw);
    } catch (e) {
      return;
    }
    var labels = radarData.labels;
    var datasets = radarData.datasets;
    if (!labels || !datasets || labels.length < 2) return;

    var wrap = canvas.parentElement;
    var rect = (wrap && wrap.getBoundingClientRect) ? wrap.getBoundingClientRect() : { width: 280, height: 220 };
    var w = Math.max(120, Math.floor(rect.width || 280));
    var h = Math.max(100, Math.floor(rect.height || 220));
    var dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var cx = w / 2;
    var cy = h / 2;
    var maxR = Math.min(w, h) * 0.36;
    var n = labels.length;
    var angles = labels.map(function (_, i) {
      return (Math.PI * 2 * i / n) - Math.PI / 2;
    });

    ctx.strokeStyle = 'rgba(233,247,239,0.06)';
    ctx.lineWidth = 1;
    for (var ring = 1; ring <= 4; ring++) {
      var rr = maxR * ring / 4;
      ctx.beginPath();
      angles.forEach(function (a, i) {
        var x = cx + Math.cos(a) * rr;
        var y = cy + Math.sin(a) * rr;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.stroke();
    }

    angles.forEach(function (a, i) {
      var x = cx + Math.cos(a) * maxR;
      var y = cy + Math.sin(a) * maxR;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();
      ctx.fillStyle = '#8cb39f';
      ctx.font = '11px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      var lx = cx + Math.cos(a) * (maxR + 18);
      var ly = cy + Math.sin(a) * (maxR + 18);
      ctx.fillText(labels[i], lx, ly);
    });

    datasets.forEach(function (ds) {
      var color = ds.color || '#34d399';
      var data = ds.data || [];
      ctx.beginPath();
      angles.forEach(function (a, i) {
        var v = Math.max(0, Math.min(100, Number(data[i]) || 0));
        var r = maxR * v / 100;
        var px = cx + Math.cos(a) * r;
        var py = cy + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.fillStyle = hexToRgba(color, 0.18);
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
      angles.forEach(function (a, i) {
        var v = Math.max(0, Math.min(100, Number(data[i]) || 0));
        var r = maxR * v / 100;
        ctx.beginPath();
        ctx.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, 2, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      });
    });
  }

  function paintRadar() {
    var canvas = document.getElementById('radarChart');
    if (!canvas || !canvas.getAttribute('data-radar')) return;
    drawRadarCanvas(canvas);
    if (!radarResizeBound) {
      radarResizeBound = true;
      window.addEventListener('resize', function () {
        var c = document.getElementById('radarChart');
        if (c && c.getAttribute('data-radar')) drawRadarCanvas(c);
      });
    }
  }

  window.__paintSparks = paintSparks;
  window.__paintRadar = paintRadar;
})();
