// The blue loading bar at the top of every page.
// Every page load fills it (pure CSS). Here we restart it when the visitor
// leaves the page, so it creeps forward while the next page is loading.
(function () {
  var root = document.documentElement;

  // Also tells the rest of the page a new page is on its way ("someless:navigate"),
  // so the signed-in pages can show their loader (page-loader.js).
  function startLoading() {
    root.classList.remove("is-loading");
    void root.offsetWidth; // restart the CSS animation
    root.classList.add("is-loading");
    document.dispatchEvent(new CustomEvent("someless:navigate"));
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target && link.target !== "_self") return;
    if (link.hasAttribute("download") || link.origin !== location.origin) return;
    if (link.hash && link.pathname === location.pathname) return;
    startLoading();
  });

  document.addEventListener("submit", function (event) {
    if (!event.defaultPrevented) startLoading();
  });

  // Coming back with the Back button can show the page from cache, still "loading".
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) root.classList.remove("is-loading");
  });
})();
