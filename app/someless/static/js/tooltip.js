// Tips: a word of help beside something (the ? next to a domain's status), in a small card in
// the panel's own look instead of the browser's plain tooltip. Any element with data-tip shows
// it on hover, and on focus, for the keyboard and for a tap on a phone. The card sits on the
// page itself, above the element (below it when there's no room), so a table that clips its
// rows can't cut it off. The pointer can move onto the card to read it; moving away, Escape,
// scrolling or leaving the page puts it away.
(function () {
  var GAP = 10;   // between the element and the card
  var EDGE = 12;  // the least room kept between the card and the window's edges
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("aria-hidden", "true"); // the element's own label says it to screen readers
  document.body.appendChild(tip);
  var shownFor = null;
  var hideTimer = null;

  function show(element) {
    clearTimeout(hideTimer);
    if (shownFor === element) return;
    shownFor = element;
    tip.textContent = element.getAttribute("data-tip");
    tip.classList.remove("is-shown");
    tip.style.left = "0px";
    tip.style.top = "0px";
    var box = element.getBoundingClientRect();
    var width = tip.offsetWidth;
    var height = tip.offsetHeight;
    var below = box.top - GAP - height < EDGE;
    var middle = box.left + box.width / 2;
    var left = Math.max(EDGE, Math.min(middle - width / 2, window.innerWidth - width - EDGE));
    tip.style.left = left + "px";
    tip.style.top = (below ? box.bottom + GAP : box.top - GAP - height) + "px";
    tip.style.setProperty("--arrow-x", Math.max(16, Math.min(middle - left, width - 16)) + "px");
    tip.setAttribute("data-side", below ? "below" : "above");
    void tip.offsetWidth; // fade in from where it now is
    tip.classList.add("is-shown");
  }

  function hide(soon) {
    clearTimeout(hideTimer);
    if (!shownFor) return;
    hideTimer = setTimeout(function () {
      shownFor = null;
      tip.classList.remove("is-shown");
    }, soon ? 140 : 0);
  }

  document.addEventListener("pointerover", function (event) {
    if (tip.contains(event.target)) return clearTimeout(hideTimer);
    var element = event.target.closest("[data-tip]");
    if (element) show(element);
  });
  document.addEventListener("pointerout", function (event) {
    var from = event.target.closest("[data-tip]") || (tip.contains(event.target) ? tip : null);
    if (!from || (event.relatedTarget && (from.contains(event.relatedTarget) || tip.contains(event.relatedTarget)))) return;
    if (from === tip || from === shownFor) {
      if (shownFor && shownFor === document.activeElement) return; // focused: stays until it loses focus
      hide(true);
    }
  });
  document.addEventListener("focusin", function (event) {
    var element = event.target.closest && event.target.closest("[data-tip]");
    if (element) show(element);
  });
  document.addEventListener("focusout", function (event) {
    if (event.target === shownFor) hide(false);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && shownFor) hide(false);
  });
  window.addEventListener("scroll", function () { hide(false); }, { passive: true });
  window.addEventListener("resize", function () { hide(false); });
  document.addEventListener("someless:navigate", function () { hide(false); });
})();
