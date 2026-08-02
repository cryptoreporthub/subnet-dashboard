(function () {
  if (window.matchMedia('(min-width: 900px)').matches) return;
  var dock = document.querySelector('.thumb-dock');
  if (!dock || !('IntersectionObserver' in window)) return;

  var links = Array.prototype.slice.call(dock.querySelectorAll('.thumb-dock__link'));
  var sections = links.map(function (link) {
    var id = (link.getAttribute('href') || '').slice(1);
    return id ? document.getElementById(id) : null;
  }).filter(Boolean);
  if (!sections.length) return;

  var activeId = '';
  var ratios = {};

  function setActive(id) {
    if (!id || id === activeId) return;
    activeId = id;
    links.forEach(function (link) {
      var on = link.getAttribute('href') === '#' + id;
      if (on) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
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
