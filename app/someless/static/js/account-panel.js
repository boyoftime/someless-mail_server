// The sphere on the divider at the bottom of the side menu shows and hides the account
// options below it (signed-in name, Settings, Log out); style.css unfolds them smoothly.
// While hidden, the options can't be reached with the keyboard. The server renders them
// open on the Settings page. Each click also sends a burst of light out of the sphere.
(function () {
  var toggle = document.querySelector("[data-account-toggle]");
  var panel = document.getElementById("account-panel");
  if (!toggle || !panel) return;
  var divider = toggle.closest(".account-divider");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var flareTimer = null;

  // A burst of light each time the sphere is clicked (.is-flaring in style.css).
  function flare() {
    if (reduceMotion) return;
    [toggle, divider].forEach(function (el) {
      if (!el) return;
      el.classList.remove("is-flaring");
      void el.offsetWidth; // restart the burst on quick repeated clicks
      el.classList.add("is-flaring");
    });
    clearTimeout(flareTimer);
    flareTimer = setTimeout(function () {
      toggle.classList.remove("is-flaring");
      if (divider) divider.classList.remove("is-flaring");
    }, 900);
  }

  function show(open) {
    panel.classList.toggle("is-open", open);
    panel.inert = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  toggle.addEventListener("click", function () {
    flare();
    show(toggle.getAttribute("aria-expanded") !== "true");
  });
  show(toggle.getAttribute("aria-expanded") === "true");
})();
