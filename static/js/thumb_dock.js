(function () {
  'use strict';

  if (window.matchMedia('(min-width: 900px)').matches) return;

  var dock = document.querySelector('.thumb-dock');
  if (!dock) return;

  var links = Array.prototype.slice.call(dock.querySelectorAll('.thumb-dock__link'));
  if (!links.length) return;

  function openDrawer(id) {
    if (!id) return;
    var drawer = document.getElementById(id);
    if (drawer && drawer.tagName === 'DETAILS') drawer.open = true;
  }

  links.forEach(function (link) {
    link.addEventListener('click', function () {
      openDrawer(link.getAttribute('data-open-drawer'));
    });
  });

  function sectionForLink(link) {
    var drawerId = link.getAttribute('data-open-drawer');
    if (drawerId) {
      var drawer = document.getElementById(drawerId);
      if (drawer) return drawer;
    }
    var sectionId = link.getAttribute('data-thumb-section') || (link.getAttribute('href') || '').slice(1);
    return sectionId ? document.getElementById(sectionId) : null;
  }

  var sections = links.map(sectionForLink).filter(Boolean);
  if (!sections.length) return;

  var activeId = '';
  var ratios = {};

  function setActive(id) {
    if (!id || id === activeId) return;
    activeId = id;
    links.forEach(function (link) {
      var section = sectionForLink(link);
      var on = section && section.id === id;
      if (on) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }

  if (!('IntersectionObserver' in window)) {
    setActive(sections[0].id);
    return;
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        ratios[entry.target.id] = entry.intersectionRatio;
      });
      var best = sections[0];
      sections.forEach(function (section) {
        if ((ratios[section.id] || 0) > (ratios[best.id] || 0)) best = section;
      });
      if ((ratios[best.id] || 0) > 0) setActive(best.id);
    },
    { root: null, rootMargin: '-35% 0px -40% 0px', threshold: [0, 0.1, 0.25, 0.5] }
  );

  sections.forEach(function (section) {
    observer.observe(section);
  });
  setActive(sections[0].id);
})();
