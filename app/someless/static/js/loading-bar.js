// The blue loading bar at the top of every page.
// Every page load fills it (pure CSS). Here we restart it when the visitor
// leaves the page, so it creeps forward while the next page is loading.
// page-swap.js brings the signed-in pages in without a reload, and uses
//   somelessLoadingBar.start()   (Back and Forward)
//   somelessLoadingBar.finish()  (the new page is in: run to the end and fade)
(function () {
  var root = document.documentElement;

  // Also tells the rest of the page a new page is on its way ("someless:navigate"),
  // so the signed-in pages can show their loader (page-loader.js).
  function startLoading() {
    root.classList.remove("is-loading", "is-finishing");
    void root.offsetWidth; // restart the CSS animation
    root.classList.add("is-loading");
    document.dispatchEvent(new CustomEvent("someless:navigate"));
  }

  // From wherever the bar had crept to, on to the end (style.css, .is-finishing).
  function finishLoading() {
    if (!root.classList.contains("is-loading")) return;
    var fill = document.querySelector(".loading-bar-fill");
    var full = fill && fill.parentElement.getBoundingClientRect().width;
    var from = full ? (fill.getBoundingClientRect().width / full) * 100 : 0;
    root.style.setProperty("--bar-from", from.toFixed(2) + "%");
    root.classList.remove("is-loading");
    root.classList.add("is-finishing");
  }

  window.somelessLoadingBar = { start: startLoading, finish: finishLoading };

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
    if (event.persisted) root.classList.remove("is-loading", "is-finishing");
  });
})();
