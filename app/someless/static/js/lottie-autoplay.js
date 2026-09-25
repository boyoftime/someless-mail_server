// Plays every [data-lottie] animation on the page in a loop.
// - data-lottie-light: a second file for the light theme (Lottie colours are baked into the
//   file). The theme is the one the admin picked (<html data-theme>); when it changes
//   (theme.js sends "someless:theme"), those animations switch files on the spot.
// - With reduced motion it shows a still frame from the middle, or, for elements marked
//   data-lottie-motion-only, nothing at all, so their plain fallback stays in place.
// A loaded animation gets the class "is-playing".
(function () {
  if (!window.lottie) return;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var themed = []; // animations with a light version: { el, animation }

  function fileFor(el) {
    var light = document.documentElement.dataset.theme === "light";
    return light && el.dataset.lottieLight ? el.dataset.lottieLight : el.dataset.lottie;
  }

  function play(el) {
    var animation = window.lottie.loadAnimation({
      container: el,
      renderer: "svg",
      loop: true,
      autoplay: !reduceMotion,
      path: fileFor(el),
    });
    animation.addEventListener("DOMLoaded", function () {
      el.classList.add("is-playing");
      if (reduceMotion) animation.goToAndStop(Math.floor(animation.totalFrames / 2), true);
    });
    return animation;
  }

  document.querySelectorAll("[data-lottie]").forEach(function (el) {
    if (reduceMotion && el.hasAttribute("data-lottie-motion-only")) return;
    var animation = play(el);
    if (el.dataset.lottieLight) themed.push({ el: el, animation: animation });
  });

  document.addEventListener("someless:theme", function () {
    themed.forEach(function (item) {
      item.animation.destroy();
      item.animation = play(item.el);
    });
  });
})();
