// Page flips: a link marked data-page-flip turns the main area over like a page to the one it
// leads to (SMTP & API and its guide). A flash of light on the link, the page turns away until
// it's edge-on, and the new one turns in from the other side once page-swap.js has brought it
// in. The loader's veil stays away (page-loader.js): the turning is the wait.
// data-page-flip="back" turns the other way. With reduced motion, the new page just comes.
(function () {
  var root = document.documentElement;
  var main = document.getElementById("app-main");
  if (!main || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var direction = null; // "forward" or "back" while a page turns
  var giveUp = null;

  // The page turns about the middle of what's on the screen, not of the whole (long) page.
  function turnAbout(scrollTop) {
    var top = main.getBoundingClientRect().top + window.scrollY;
    main.style.transformOrigin = "50% " + (scrollTop + window.innerHeight / 2 - top) + "px";
  }

  function settle() {
    main.classList.remove("flip-out", "flip-out-back", "flip-in", "flip-in-back");
    main.style.transformOrigin = "";
    root.classList.remove("is-page-flipping");
    direction = null;
  }

  // Before page-swap.js and the loading bar see the click (capture)
  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[data-page-flip]");
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    direction = link.dataset.pageFlip === "back" ? "back" : "forward";
    link.classList.remove("is-flashing");
    void link.offsetWidth; // flash again, even on a second click
    link.classList.add("is-flashing");
    root.classList.add("is-page-flipping");
    turnAbout(window.scrollY);
    main.classList.remove("flip-in", "flip-in-back");
    main.classList.add(direction === "back" ? "flip-out-back" : "flip-out");
    // If the page never comes (no connection), turn this one back rather than leave it edge-on
    clearTimeout(giveUp);
    giveUp = setTimeout(function () {
      if (main.classList.contains("flip-out") || main.classList.contains("flip-out-back")) settle();
    }, 10000);
  }, true);

  // The new page is in (page-swap.js sets the main area's classes afresh): turn it in
  document.addEventListener("someless:swap", function () {
    if (!direction) return;
    clearTimeout(giveUp);
    turnAbout(0); // page-swap.js scrolls a new page to the top
    main.classList.add(direction === "back" ? "flip-in-back" : "flip-in");
    root.classList.remove("is-page-flipping");
    direction = null;
  });

  main.addEventListener("animationend", function (event) {
    if (event.target === main && /^page-flip-in/.test(event.animationName)) settle();
  });
})();
