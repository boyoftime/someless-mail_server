// Side menu.
// - Wide screens: always docked on the left. The hamburger in its corner collapses it to
//   a slim strip of icons and expands it again (the page slides along). Expanded is the
//   default; the choice is remembered until log out.
// - Narrow screens: the hamburger in the top bar slides it over the page. The hamburger in
//   its corner, Escape or a click outside slide it away; the keyboard stays inside it
//   while open, and focus goes back to the top bar hamburger afterwards.
// The page switches between the two automatically when the window is resized.
(function () {
  var menu = document.getElementById("side-menu");
  var topButton = document.querySelector("[data-menu-open]");
  var sideButton = menu && menu.querySelector("[data-menu-toggle]");
  if (!menu || !topButton || !sideButton || typeof menu.showModal !== "function") return;
  var root = document.documentElement;
  var panel = menu.querySelector(".side-menu-panel");
  var WIDE = window.matchMedia("(min-width: 1024px)"); // same width as the check in shell.html
  var KEY = "someless-menu"; // "collapsed" once collapsed to icons
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var closeTimer = null; // backup in case the slide-out animation never ends
  var quietClose = false; // closed by a resize, not by the visitor: leave focus alone

  function collapsed() {
    try { return localStorage.getItem(KEY) === "collapsed"; } catch (error) { return false; }
  }
  function remember(isCollapsed) {
    try { localStorage.setItem(KEY, isCollapsed ? "collapsed" : "expanded"); } catch (error) {}
  }

  // A quick spin of the hamburger each time it is used.
  function spin(button) {
    if (reduceMotion) return;
    button.classList.remove("is-spinning");
    void button.offsetWidth;
    button.classList.add("is-spinning");
  }

  // Wide screens: docked next to the page, expanded or as icons. Setting the attribute
  // (rather than show()) opens it without moving the keyboard focus into it.
  function dock() {
    var rail = collapsed();
    menu.classList.add("is-docked");
    menu.classList.toggle("is-rail", rail);
    if (!menu.open) menu.setAttribute("open", "");
    root.classList.add("menu-docked");
    root.classList.toggle("menu-rail", rail);
    sideButton.setAttribute("aria-expanded", rail ? "false" : "true");
    sideButton.setAttribute("aria-label", rail ? "Expand menu" : "Collapse menu");
  }

  // Narrow screens: slide over the page.
  function slideOver() {
    clearTimeout(closeTimer);
    menu.classList.remove("is-docked", "is-rail", "is-instant", "is-closing");
    if (!menu.open) menu.showModal();
    topButton.setAttribute("aria-expanded", "true");
    sideButton.setAttribute("aria-expanded", "true");
    sideButton.setAttribute("aria-label", "Close menu");
  }

  function finishClosing() {
    clearTimeout(closeTimer);
    menu.classList.remove("is-closing");
    if (menu.open) menu.close();
  }

  // Narrow screens: slide away, then really close.
  function slideAway() {
    if (!menu.open || menu.classList.contains("is-closing") || WIDE.matches) return;
    if (reduceMotion) {
      menu.close();
      return;
    }
    menu.classList.add("is-closing");
    closeTimer = setTimeout(finishClosing, 450);
  }

  // Page load or window resize: put the menu in place without any movement. Smooth
  // changes are back on two frames later, so the very first click animates like any other.
  function placeInstantly() {
    menu.classList.add("is-instant");
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { menu.classList.remove("is-instant"); });
    });
  }

  // Put the menu in the right state for the screen size.
  function fitScreen(instantly) {
    quietClose = true;
    clearTimeout(closeTimer);
    menu.classList.remove("is-closing");
    if (menu.open) menu.close();
    quietClose = false;
    menu.classList.remove("is-docked", "is-rail");
    root.classList.remove("menu-docked", "menu-rail");
    topButton.setAttribute("aria-expanded", "false");
    if (WIDE.matches) {
      if (instantly) placeInstantly();
      dock();
    }
  }

  panel.addEventListener("animationend", function (event) {
    if (event.animationName === "menu-out" && menu.classList.contains("is-closing")) finishClosing();
  });
  topButton.addEventListener("click", function () {
    spin(topButton);
    slideOver();
  });
  sideButton.addEventListener("click", function () {
    spin(sideButton);
    if (WIDE.matches) {
      remember(!collapsed());
      dock();
    } else {
      slideAway();
    }
  });
  menu.addEventListener("cancel", function (event) {
    event.preventDefault(); // Escape: slide away instead of vanishing
    slideAway();
  });
  menu.addEventListener("click", function (event) {
    if (event.target === menu && !WIDE.matches) slideAway(); // the dimmed area outside
  });
  menu.addEventListener("close", function () {
    topButton.setAttribute("aria-expanded", "false");
    if (!quietClose) setTimeout(function () { topButton.focus(); }, 0);
  });

  // Clicking a page in the menu makes its row the current one straight away (lit up, its
  // hexagon pulsing, its beam reaching the glowing edge) while that page loads, and the old
  // row goes quiet. Waiting for the next page would leave the old row lit, as if the click
  // hadn't registered. Like pineloop.
  var rows = menu.querySelectorAll("a.side-menu-item");
  var currentOnLoad = menu.querySelector("a.side-menu-item[aria-current='page']");

  function markCurrent(chosen) {
    rows.forEach(function (row) {
      if (row === chosen) row.setAttribute("aria-current", "page");
      else row.removeAttribute("aria-current");
    });
  }

  rows.forEach(function (row) {
    row.addEventListener("click", function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (row.getAttribute("aria-current") === "page") {
        // already on this page: nothing to load (on a phone, just close the menu)
        event.preventDefault();
        slideAway();
        return;
      }
      markCurrent(row);
    });
  });

  // Log out lights up as soon as it is clicked, while the logout goes through.
  // The next login starts with the menu expanded again.
  var logout = menu.querySelector("form[action$='/logout']");
  var logoutButton = menu.querySelector(".side-menu-logout");
  if (logout) {
    logout.addEventListener("submit", function () {
      try { localStorage.removeItem(KEY); } catch (error) {}
      if (logoutButton) logoutButton.classList.add("is-going");
    });
  }

  // The Back button can bring a page back exactly as it was left: show its own row as the
  // current one again, and Log out as not clicked.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    markCurrent(currentOnLoad);
    if (logoutButton) logoutButton.classList.remove("is-going");
  });

  WIDE.addEventListener("change", function () { fitScreen(true); });

  fitScreen(true);
})();
