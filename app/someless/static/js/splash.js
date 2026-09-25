// The 6-second welcome splash. The water animation, the top loading bar and the words
// all start together on one clock, then the page moves on to the login page.
// Without JavaScript, a <noscript> refresh in the page moves on after 6 seconds instead.
(function () {
  var SPLASH_MS = 6000;
  var WAIT_FOR_ANIMATION_MS = 1500;

  var main = document.querySelector(".splash-main");
  var el = document.getElementById("splash-animation");
  if (!main) return;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var animation = null;
  var started = false;

  function playAnimation() {
    if (reduceMotion) animation.goToAndStop(animation.totalFrames - 1, true);
    else animation.play();
  }

  // While the splash plays, download everything the login page needs (data-preload),
  // so it appears straight away. Browsers keep these files, see STATIC_CACHE_SECONDS.
  var preloaded = [];
  function preloadNextPage() {
    (main.dataset.preload || "").split(/\s+/).forEach(function (url) {
      if (!url) return;
      if (/\.(webp|png|jpe?g|gif|svg)(\?|$)/i.test(url)) {
        var image = new Image();
        image.src = url;
        preloaded.push(image); // keep a reference until it has loaded
      } else {
        fetch(url, { credentials: "same-origin" }).catch(function () {});
      }
    });
  }

  function start() {
    if (started) return;
    started = true;
    document.body.classList.add("is-playing");
    if (animation && animation.isLoaded) playAnimation();
    preloadNextPage();
    setTimeout(function () {
      window.location.replace(main.dataset.next);
    }, SPLASH_MS);
  }

  if (el && window.lottie) {
    animation = window.lottie.loadAnimation({
      container: el,
      renderer: "svg",
      loop: false,
      autoplay: false,
      path: el.dataset.src,
    });
    animation.addEventListener("DOMLoaded", function () {
      if (started) playAnimation(); // arrived late: play it anyway
      else start();
    });
    animation.addEventListener("data_failed", start);
  }

  // Don't hold the splash back forever if the animation file is slow or missing.
  setTimeout(start, animation ? WAIT_FOR_ANIMATION_MS : 0);
})();
