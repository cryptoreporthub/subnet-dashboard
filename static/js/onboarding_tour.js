/** First-visit product tour (driver.js). */
(function () {
  'use strict';

  var STORAGE_KEY = 'simivision_tour_done';

  function startTour() {
    if (typeof window.driver === 'undefined' || !window.driver.js) return;
    var driver = window.driver.js.driver;
    var d = driver({
      showProgress: true,
      animate: true,
      overlayOpacity: 0.65,
      steps: [
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
      ],
      onDestroyed: function () {
        try { localStorage.setItem(STORAGE_KEY, '1'); } catch (e) { /* ignore */ }
      },
    });
    d.drive();
  }

  function maybeStart() {
    try {
      if (localStorage.getItem(STORAGE_KEY) === '1') return;
    } catch (e) { /* ignore */ }
    if (document.documentElement.dataset.hydrate !== '1') return;
    setTimeout(startTour, 2200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', maybeStart);
  } else {
    maybeStart();
  }
})();
