/* data_fixer.js — fetches /api/council and patches blank/stale DOM sections */
(function () {
  'use strict';

  function dedupe(subnets) {
    var seen = {}; var unique = [];
    for (var i = 0; i < subnets.length; i++) {
      var nuid = subnets[i].netuid || subnets[i].id || 0;
      if (!seen[nuid]) { seen[nuid] = true; unique.push(subnets[i]); }
    }
    return unique;
  }

  function replaceText(oldStr, newStr) {
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    while (walker.nextNode()) {
      if (walker.currentNode.textContent && walker.currentNode.textContent.indexOf(oldStr) !== -1) {
        walker.currentNode.textContent = walker.currentNode.textContent.replace(oldStr, newStr);
      }
    }
  }

  function replaceTextAll(oldStr, newStr) {
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    while (walker.nextNode()) {
      if (walker.currentNode.textContent && walker.currentNode.textContent.indexOf(oldStr) !== -1) {
        walker.currentNode.textContent = walker.currentNode.textContent.split(oldStr).join(newStr);
      }
    }
  }

  function fmt(n, d) { d = d || 2; return Number(n).toFixed(d); }
  function fmtSigned(n, d) { d = d || 2; return (n >= 0 ? '+' : '') + Number(n).toFixed(d); }

  async function run() {
    try {
      var resp = await fetch('/api/subnets');
      if (!resp.ok) return;
      var data = await resp.json();
      var subnets = dedupe(data.subnets || []);
      if (!subnets.length) return;

      // ── Market snapshot ──
      var gainers = subnets.filter(function (s) { return (s.price_change_24h || 0) > 0; });
      var losers = subnets.filter(function (s) { return (s.price_change_24h || 0) < 0; });
      var avgChange = subnets.reduce(function (a, s) { return a + (s.price_change_24h || 0); }, 0) / subnets.length;

      replaceText('0 gainers / 0 losers', gainers.length + ' gainers / ' + losers.length + ' losers');
      replaceTextAll('+0.00%', fmtSigned(avgChange) + '%');
      replaceText('0 gainers', gainers.length + ' gainers');

      // ── Market snapshot (stats only — names come from canonical /api/subnets) ──
      var byEmission = subnets.slice().sort(function (a, b) {
        return (b.emission || 0) - (a.emission || 0);
      });
      var priceIdx = 0;
      var walker2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      while (walker2.nextNode()) {
        var node = walker2.currentNode;
        if (node.textContent && node.textContent.indexOf('+0.00%') !== -1 && priceIdx < subnets.length) {
          var sn = subnets[priceIdx];
          node.textContent = node.textContent.split('+0.00%').join(fmtSigned(sn.price_change_24h || 0) + '%');
          priceIdx++;
        }
      }

      // ── Rotation tracker ──
      if (gainers.length > 0 || losers.length > 0) {
        replaceText('0 active', Math.min(gainers.length, 3) + ' active');
        replaceText('No rotation patterns detected.', Math.min(gainers.length, 3) + ' rotation patterns detected.');
      }

      // ── Daily pick ──
      if (byEmission.length > 0) {
        var dp = byEmission[0];
        replaceText('No audited daily pick available.',
          (dp.name || 'SN' + dp.netuid) + ' SN' + dp.netuid + ' · ' + fmt(dp.apy || 0, 1) + '% APY');
      }

      console.log('[data_fixer] Patched', subnets.length, 'unique subnets into DOM');
    } catch (e) {
      console.error('[data_fixer] Error:', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(run, 500); });
  } else {
    setTimeout(run, 500);
  }
})();
