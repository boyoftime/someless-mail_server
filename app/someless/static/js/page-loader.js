// The loader over the signed-in pages while the next page loads: a soft veil with the
// loading animation, from the moment a link is clicked or a form is sent until the next
// page appears. loading-bar.js says when that happens ("someless:navigate"). The animation
// waits, paused and hidden, until it is needed.
(function () {
  var loader = document.getElementById("page-loader");
  if (!loader || typeof loader.showModal !== "function") return;
  var holder = loader.querySelector("[data-loader-animation]");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var animation = null;

  if (window.lottie && holder) {
    animation = window.lottie.loadAnimation({
      container: holder,
      renderer: "svg",
      loop: true,
      autoplay: false,
      path: holder.dataset.loaderAnimation,
    });
  }

  function show() {
    if (loader.open) return;
    loader.showModal();
    if (!animation) return;
    if (reduceMotion) animation.goToAndStop(Math.floor(animation.totalFrames / 2), true);
    else animation.play();
  }

  function hide() {
    if (animation) animation.pause();
    if (loader.open) loader.close();
  }

  document.addEventListener("someless:navigate", show);

  // The Back button can bring a page back exactly as it was left, loader and all.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) hide();
  });
})();
