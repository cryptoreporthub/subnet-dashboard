/* SimiVision jargon glossary + tooltip interaction */
(function () {
  "use strict";

  const GLOSSARY = {
    "APY": "Annual Percentage Yield — the estimated yearly return from staking or yield farming on this subnet.",
    "emission": "Emission — the amount of TAO rewarded to this subnet per day, reflecting network-level incentives.",
    "RSI": "Relative Strength Index — a momentum oscillator. Values below 30 suggest oversold conditions; above 70 suggest overbought.",
    "MACD": "Moving Average Convergence Divergence — a trend-following indicator that shows the relationship between two moving averages.",
    "oversold": "Oversold — price has fallen sharply and may be due for a bounce or reversal.",
    "overbought": "Overbought — price has risen sharply and may be due for a pullback or consolidation.",
    "convergence": "Convergence — multiple technical indicators aligning to suggest the same directional setup.",
    "momentum": "Momentum — the rate and strength of recent price movement.",
    "stochastic": "Stochastic Oscillator — compares a closing price to its price range over time to identify overbought/oversold levels.",
    "Bollinger": "Bollinger Bands — volatility bands placed above and below a moving average; squeezes can signal impending moves.",
    "MFI": "Money Flow Index — a volume-weighted RSI that measures buying and selling pressure.",
    "CCI": "Commodity Channel Index — identifies cyclical turns; extreme readings can signal overbought/oversold conditions.",
    "Williams": "Williams %R — a momentum indicator that identifies overbought/oversold levels on a 0 to -100 scale.",
    "Keltner": "Keltner Channels — volatility-based envelopes around an exponential moving average.",
    "MA cross": "Moving Average Crossover — occurs when a short-term moving average crosses above or below a longer-term one.",
    "HOT": "HOT signal — a bullish setup where multiple short-term indicators align.",
    "SELL ALERT": "SELL ALERT — a bearish warning triggered by overbought convergence or distribution signals.",
    "conviction": "Conviction — a composite score reflecting how strongly the model favors this pick.",
    "predicted": "Predicted move — a forecast framed as +/-X% within N hours, tracked by the learning loop.",
    "market cap": "Market Cap — total value of the subnet token calculated from price and circulating supply.",
    "volume": "Volume — the amount of the subnet token traded over the selected period.",
    "sentiment": "Social Sentiment — a qualitative read of community chatter around the subnet.",
    "TAO": "TAO — the native token of the Bittensor network.",
    "subnet": "Subnet — a specialized market or application running on the Bittensor network.",
  };

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function wrapTerm(text, term, definition) {
    const escapedTerm = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp("\\b(" + escapedTerm + ")\\b", "gi");
    return text.replace(re, function (match) {
      return (
        '<span class="jargon-term" tabindex="0">' +
        escapeHtml(match) +
        '<span class="simi-tooltip"><strong>' +
        escapeHtml(term) +
        "</strong>" +
        escapeHtml(definition) +
        "</span></span>"
      );
    });
  }

  function applyJargonTooltips(root) {
    root = root || document.body;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    const nodes = [];
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement && node.parentElement.closest(".jargon-term")) continue;
      nodes.push(node);
    }
    nodes.forEach(function (textNode) {
      let html = escapeHtml(textNode.nodeValue);
      Object.keys(GLOSSARY).forEach(function (term) {
        html = wrapTerm(html, term, GLOSSARY[term]);
      });
      if (html.indexOf("jargon-term") !== -1) {
        const wrapper = document.createElement("span");
        wrapper.innerHTML = html;
        textNode.parentNode.replaceChild(wrapper, textNode);
      }
    });
  }

  function renderTopPicks() {
    const container = document.querySelector(".picks");
    if (!container) return;
    fetch("/api/top-picks")
      .then(function (r) {
        return r.json();
      })
      .then(function (payload) {
        const data = (payload && payload.data) || {};
        const hour = data.hour;
        const day = data.day;
        if (!hour && !day) return;
        container.innerHTML = "";
        [hour, day].forEach(function (pick, idx) {
          if (!pick) return;
          const timeframe = idx === 0 ? "HOUR" : "DAY";
          const sellActive = pick.sell && pick.sell.active;
          const hotActive = pick.hot && pick.hot.active;
          const rec = sellActive ? "SELL" : hotActive ? "BUY" : "HOLD";
          const tagClass = sellActive ? "tag-sell" : hotActive ? "tag-buy" : "tag-hold";
          const pill = sellActive
            ? '<span class="pill-sell">• SELL ALERT</span>'
            : hotActive
            ? '<span class="pill-hot">• HOT</span>'
            : "";
          const pred = pick.signal_impact && pick.signal_impact.net_predicted_pct !== undefined
            ? "→ predicted to move " + (pick.signal_impact.net_predicted_pct >= 0 ? "+" : "") +
              pick.signal_impact.net_predicted_pct.toFixed(1) + "%"
            : "";
          const reasons = (pick.hot && pick.hot.reasons) || (pick.sell && pick.sell.reasons) || [];
          const reasonsHtml = reasons.length
            ? '<ul class="reasons">' + reasons.map(function (r) { return "<li>" + escapeHtml(r) + "</li>"; }).join("") + "</ul>"
            : "";
          const card = document.createElement("div");
          card.className = "card pick" + (sellActive ? " sell-accent" : "");
          card.innerHTML =
            '<div class="pick-rank">#' + (pick.rank || 1) + "</div>" +
            '<div class="pick-name">' + escapeHtml(pick.name || "Unknown") + "</div>" +
            '<div class="pick-meta">SN' + (pick.netuid || "—") + " · " +
            (pick.emission !== undefined ? pick.emission.toFixed(2) : "0.00") + " TAO/day · " +
            (pick.apy !== undefined ? pick.apy.toFixed(1) : "0.0") + "% APY · " + timeframe + "</div>" +
            '<div class="pick-row">' +
              '<div class="conviction-wrap">' +
                '<div class="conviction-lbl">SCORE ' + (pick.score !== undefined ? pick.score.toFixed(1) : "0.0") + "</div>" +
                '<div class="conviction-bar"><div class="conviction-fill" style="width:' + Math.min(100, Math.max(0, pick.score || 0)) + '%"></div></div>' +
              "</div>" +
            "</div>" +
            reasonsHtml +
            '<div class="tags"><span class="tag ' + tagClass + '">' + rec + "</span>" + pill + "</div>" +
            (pred ? '<div class="pred-line">' + escapeHtml(pred) + "</div>" : "");
          container.appendChild(card);
        });
        applyJargonTooltips(container);
      })
      .catch(function (err) {
        console.warn("Top picks fetch failed:", err);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      applyJargonTooltips();
      renderTopPicks();
    });
  } else {
    applyJargonTooltips();
    renderTopPicks();
  }

  window.SimiVisionJargon = {
    glossary: GLOSSARY,
    apply: applyJargonTooltips,
    renderTopPicks: renderTopPicks,
  };
})();
