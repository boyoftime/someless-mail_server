// The theme switch in the side menu: dark (the default) or light, for every page. The choice
// is kept in the "theme" cookie, so the server draws each page in it from the start, the
// login page after logging out included. Switching recolours the page on the spot, with a
// soft cross-fade where the browser can do one; animations that have a light version follow
// along (lottie-autoplay.js listens for "someless:theme").
(function () {
  var toggle = document.querySelector("[data-theme-switch]");
  if (!toggle) return;
  var root = document.documentElement;
  var meta = document.querySelector('meta[name="color-scheme"]');
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function apply(theme) {
    root.dataset.theme = theme;
    if (meta) meta.content = theme;
    toggle.setAttribute("aria-checked", theme === "dark" ? "true" : "false");
    document.cookie = "theme=" + theme + "; path=/; max-age=31536000; samesite=lax" +
      (location.protocol === "https:" ? "; secure" : "");
    document.dispatchEvent(new CustomEvent("someless:theme", { detail: theme }));
  }

  toggle.addEventListener("click", function () {
    var next = root.dataset.theme === "light" ? "dark" : "light";
    if (document.startViewTransition && !reduceMotion) {
      document.startViewTransition(function () { apply(next); });
    } else {
      apply(next);
    }
  });
})();
