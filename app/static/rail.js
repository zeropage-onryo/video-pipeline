/* app/static/rail.js — tiny, no framework (matches house style).
   The rail's active state is set server-side (active_nav in each route's context).
   This is only a safety-net fallback that highlights by URL if a route forgot to
   pass active_nav, plus keyboard focus niceties. */
(function () {
  var items = document.querySelectorAll('.rail-item');
  if (![].some.call(items, function (a) { return a.classList.contains('active'); })) {
    var path = location.pathname;
    [].forEach.call(items, function (a) {
      var href = a.getAttribute('href');
      if (href && href !== '/' && path.indexOf(href) === 0) a.classList.add('active');
    });
  }
})();
