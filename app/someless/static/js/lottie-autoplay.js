// Plays every [data-lottie] animation on the page in a loop.
// With reduced motion, shows a still frame from the middle instead.
(function () {
  if (!window.lottie) return;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  document.querySelectorAll("[data-lottie]").forEach(function (el) {
    var animation = window.lottie.loadAnimation({
      container: el,
      renderer: "svg",
      loop: true,
      autoplay: !reduceMotion,
      path: el.dataset.lottie,
    });
    if (reduceMotion) {
      animation.addEventListener("DOMLoaded", function () {
        animation.goToAndStop(Math.floor(animation.totalFrames / 2), true);
      });
    }
  });
})();
