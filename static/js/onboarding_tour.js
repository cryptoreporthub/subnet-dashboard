/** First-visit product tour (driver.js). */
(function () {
  'use strict';

  var STORAGE_KEY = 'simivision_tour_done';

  var TOUR_STEPS = [
    {
      element: '#section-daily-pick',
      popover: {
        title: 'Daily call',
        description: 'Today\'s audited council decision — HOLD means the gate did not clear, not a broken page.',
        side: 'bottom',
      },
    },
    {
      element: '#section-living-focus',
      popover: {
        title: 'Living Focus',
        description: 'Four beats on the subnet in play: Focus · Contest · Prove it · Watch us update. Lane judges vs council weights are labeled separately.',
        side: 'top',
      },
    },
    {
      element: '#section-brain-letter',
      popover: {
        title: 'Brain letter',
        description: 'Morning brief from graded memory — what changed, today\'s call citation, and the Next outlook for this window.',
        side: 'top',
      },
    },
  ];

  function resolveSteps() {
    return TOUR_STEPS.filter(function (step) {
      if (!step.element) return true;
      try {
        return !!document.querySelector(step.element);
      } catch (e) {
        return false;
      }
    });
  }

  // Explicit, user-initiated only — no auto-start timer. The tour used to fire
  // ~2.2s after first load and cover the Daily call / footer unprompted; now it
  // runs only when the visitor asks (help button / ?tour=1), so a first visit is
  // never hijacked. Completing it is still remembered to suppress the ?tour=1
  // replay unless the visitor opts back in via the help button.
  function startTour() {
    if (typeof window.driver === 'undefined' || !window.driver.js) return;
    var steps = resolveSteps();
    if (!steps.length) return;
    var driver = window.driver.js.driver;
    var d = driver({
      showProgress: true,
      animate: true,
      overlayOpacity: 0.55,
      steps: steps,
      onDestroyed: function () {
        try { localStorage.setItem(STORAGE_KEY, '1'); } catch (e) { /* ignore */ }
      },
    });
    d.drive();
  }

  // Public entry points.
  //  - help button: always allowed to (re)start the tour.
  //  - ?tour=1: only if not already completed in this browser.
  function startOnDemand() {
    startTour();
  }

  function startIfRequested() {
    try {
      if (localStorage.getItem(STORAGE_KEY) === '1') return;
    } catch (e) { /* ignore */ }
    if (document.documentElement.dataset.hydrate !== '1') return;
    if (window.location.search.indexOf('tour=1') === -1) return;
    startTour();
  }

  function onDemand() {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', startOnDemand);
    } else {
      startOnDemand();
    }
  }

  window.SimiTour = { start: onDemand };

  // Header "?" help button — explicit opt-in to (re)start the tour.
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('tour-trigger');
    if (btn) btn.addEventListener('click', startOnDemand);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startIfRequested);
  } else {
    startIfRequested();
  }
})();
