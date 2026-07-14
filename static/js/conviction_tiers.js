/* Canonical conviction tier cutoffs — keep in sync with Jinja templates (75/55/35). */
(function (global) {
  'use strict';

  var THRESHOLDS = { cyan: 75, lime: 55, gold: 35 };

  function confTier(conf) {
    var c = Number(conf);
    if (c <= 1) c *= 100;
    c = Math.round(c);
    if (c > THRESHOLDS.cyan) return { tier: 'tier-cyan', conf: c };
    if (c > THRESHOLDS.lime) return { tier: 'tier-lime', conf: c };
    if (c > THRESHOLDS.gold) return { tier: 'tier-gold', conf: c };
    return { tier: 'tier-red', conf: c };
  }

  global.ConvictionTiers = { THRESHOLDS: THRESHOLDS, confTier: confTier };
})(typeof window !== 'undefined' ? window : this);
