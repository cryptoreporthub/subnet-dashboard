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
            title: 'Council decision',
            description: 'Today\'s audited call lives here — HOLD means the gate did not clear, not a broken page.',
            side: 'bottom',
          },
        },
        {
          element: '#section-simivision-picks',
          popover: {
            title: 'Council is weighing',
            description: 'Names still on the table — how close each is to becoming the call, not a ranked scoreboard.',
            side: 'top',
          },
        },
        {
          element: '#section-judges',
          popover: {
            title: 'Judge panel',
            description: 'Oracle, Echo, and Pulse score each subnet — three independent lenses.',
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
