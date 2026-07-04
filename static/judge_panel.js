// Judge Council floating panel injector
(function() {
  var panel = document.createElement('div');
  panel.id = 'judge-council-panel';
  panel.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#1a1a2e;border:1px solid #c99a4b;border-radius:12px;padding:16px;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,0.5);max-width:320px;font-family:system-ui,sans-serif;';
  panel.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;"><span style="font-size:20px;">\u2696\ufe0f</span><span style="color:#c99a4b;font-weight:bold;font-size:14px;">Judge Council</span></div><p style="color:#aaa;font-size:12px;margin:0 0 10px 0;">AI judges evaluating subnet performance</p><a href="/judge-council" style="display:inline-block;background:#c99a4b;color:#1a1a2e;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:bold;">View Council \u2192</a>';
  document.body.appendChild(panel);
})();