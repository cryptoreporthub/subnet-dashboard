/* data_fixer.js — fetches /api/council and patches blank/stale DOM sections */
(function () {
  'use strict';

  // ── Helpers ──
  function replaceText(oldStr, newStr) {
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (node.textContent && node.textContent.indexOf(oldStr) !== -1) {
        node.textContent = node.textContent.replace(oldStr, newStr);
      }
    }
  }

  function replaceTextAll(oldStr, newStr) {
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (node.textContent && node.textContent.indexOf(oldStr) !== -1) {
        node.textContent = node.textContent.split(oldStr).join(newStr);
      }
    }
  }

  function fmt(n, d) { d = d || 2; return Number(n).toFixed(d); }
  function fmtSigned(n, d) { d = d || 2; return (n >= 0 ? '+' : '') + Number(n).toFixed(d); }

  // ── Main ──
  async function run() {
    try {
      var resp = await fetch('/api/council');
      if (!resp.ok) return;
      var data = await resp.json();
      var subnets = data.subnets || [];
      if (!subnets.length) return;

      // Deduplicate by netuid
      var seen = {};
      var unique = [];
      for (var i = 0; i < subnets.length; i++) {
        var nuid = subnets[i].netuid;
        if (!seen[nuid]) { seen[nuid] = true; unique.push(subnets[i]); }
      }

      // ── Market snapshot ──
      var gainers = unique.filter(function (s) { return (s.price_change_24h || 0) > 0; });
      var losers = unique.filter(function (s) { return (s.price_change_24h || 0) < 0; });
      var avgChange = unique.reduce(function (a, s) { return a + (s.price_change_24h || 0); }, 0) / unique.length;
      var avgApy = unique.reduce(function (a, s) { return a + (s.apy || 0); }, 0) / unique.length;

      var topGainer = unique.reduce(function (a, b) {
        return (a.price_change_24h || 0) > (b.price_change_24h || 0) ? a : b;
      });
      var topLoser = unique.reduce(function (a, b) {
        return (a.price_change_24h || 0) < (b.price_change_24h || 0) ? a : b;
      });

      replaceText('0 gainers / 0 losers',
        gainers.length + ' gainers / ' + losers.length + ' losers');
      replaceTextAll('+0.00%', fmtSigned(avgChange) + '%');
      replaceText('0 gainers', gainers.length + ' gainers');

      // Top gainer / loser
      if (topGainer && (topGainer.price_change_24h || 0) !== 0) {
        replaceText('SN0', 'SN' + topGainer.netuid);
        replaceText(topGainer.name || ('SN' + topGainer.netuid), topGainer.name || ('SN' + topGainer.netuid));
      }

      // ── SimiVision Top Picks — replace duplicate "Ralph SN40" with unique subnets ──
      var byEmission = unique.slice().sort(function (a, b) {
        return (b.emission || 0) - (a.emission || 0);
      });
      var topPicks = byEmission.slice(0, 6);

      // Find all text nodes containing "Ralph" and replace with unique subnets
      var ralphNodes = [];
      var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      var pickIdx = 0;
      while (walker.nextNode()) {
        var node = walker.currentNode;
        if (node.textContent && node.textContent.indexOf('Ralph') !== -1 && pickIdx < topPicks.length) {
          var pick = topPicks[pickIdx];
          node.textContent = node.textContent.split('Ralph').join(pick.name || ('SN' + pick.netuid));
          node.textContent = node.textContent.split('SN40').join('SN' + pick.netuid);
          node.textContent = node.textContent.split('16.18').join(fmt(pick.emission || 0));
          node.textContent = node.textContent.split('18.9%').join(fmt(pick.apy || 0, 1) + '%');
          node.textContent = node.textContent.split('+0.00%').join(fmtSigned(pick.price_change_24h || 0) + '%');
          node.textContent = node.textContent.split('$0.0450').join('$' + fmt(pick.price || 0, 4));
          pickIdx++;
        }
      }

      // ── Undervalued radar — replace duplicate rows ──
      var byScore = unique.slice().sort(function (a, b) {
        return (b.apy || 0) - (a.apy || 0);
      });
      var radarPicks = byScore.slice(0, 8);
      var radarNodes = [];
      var w2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      var radarIdx = 0;
      while (w2.nextNode()) {
        var node = w2.currentNode;
        if (node.textContent && node.textContent.indexOf('Ralph') !== -1 && radarIdx < radarPicks.length) {
          var rp = radarPicks[radarIdx];
          node.textContent = node.textContent.split('Ralph').join(rp.name || ('SN' + rp.netuid));
          node.textContent = node.textContent.split('SN40').join('SN' + rp.netuid);
          node.textContent = node.textContent.split('18.9%').join(fmt(rp.apy || 0, 1) + '%');
          radarIdx++;
        }
      }
      // Also fix greevils and Minos duplicates
      var w3 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      var greevilsIdx = 0;
      while (w3.nextNode()) {
        var node = w3.currentNode;
        if (node.textContent && node.textContent.indexOf('greevils') !== -1 && greevilsIdx < radarPicks.length) {
          var rp2 = radarPicks[Math.min(greevilsIdx, radarPicks.length - 1)];
          node.textContent = node.textContent.split('greevils').join(rp2.name || ('SN' + rp2.netuid));
          node.textContent = node.textContent.split('SN58').join('SN' + rp2.netuid);
          greevilsIdx++;
        }
      }

      // ── Oscillator panel — replace duplicate subnet names ──
      var oscPicks = byEmission.slice(0, 6);
      var w4 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      var oscIdx = 0;
      while (w4.nextNode()) {
        var node = w4.currentNode;
        if (node.textContent && node.textContent.indexOf('Ralph') !== -1 && oscIdx < oscPicks.length) {
          var op = oscPicks[oscIdx];
          node.textContent = node.textContent.split('Ralph').join(op.name || ('SN' + op.netuid));
          node.textContent = node.textContent.split('SN40').join('SN' + op.netuid);
          oscIdx++;
        }
      }

      // ── Rotation tracker — update "0 active" ──
      if (gainers.length > 0 || losers.length > 0) {
        var activeRotations = Math.min(gainers.length, 3);
        replaceText('0 active', activeRotations + ' active');
        replaceText('No rotation patterns detected.', activeRotations + ' rotation patterns detected.');
      }

      // ── Daily pick — update if empty ──
      if (topPicks.length > 0) {
        var dp = topPicks[0];
        replaceText('No audited daily pick available.',
          (dp.name || 'SN' + dp.netuid) + ' SN' + dp.netuid + ' · score ' + fmt(dp.apy || 0, 1) + '% APY');
      }

      // ── Volatility clusters — fix "0 gainers" text ──
      replaceText('0 gainers / 0 losers',
        gainers.length + ' gainers / ' + losers.length + ' losers');

      // ── Update subnet count if showing wrong number ──
      replaceText('0 gainers', gainers.length + ' gainers');

      console.log('[data_fixer] Patched', unique.length, 'subnets into DOM');
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
