// Smooth size changes: a dialog whose content changes (another tab, a field that shows, a list
// that comes back longer) glides to its new height instead of jumping to it:
//   somelessResize(dialog, function () { ...the change... })
// Changes that follow each other quickly glide on from wherever the last one had got to.
(function () {
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

  window.somelessResize = function (element, change) {
    if (reduceMotion || !element.getClientRects().length) return change();   // no motion, or not shown
    var from = element.getBoundingClientRect().height;
    clearTimeout(element.somelessResizeTimer);
    element.style.transition = "none";
    element.style.height = "";   // its own height, after the change
    change();
    var to = element.getBoundingClientRect().height;
    if (Math.abs(to - from) < 1) {
      element.style.transition = "";
      element.style.overflow = "";
      return;
    }
    element.style.overflow = "hidden";
    element.style.height = from + "px";
    void element.offsetHeight;   // from here...
    element.style.transition = "height 0.34s " + EASE;
    element.style.height = to + "px";   // ...to there
    element.somelessResizeTimer = setTimeout(function () {
      element.style.height = "";
      element.style.overflow = "";
      element.style.transition = "";
    }, 380);
  };
})();
