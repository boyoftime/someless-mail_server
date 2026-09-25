// The loader over the main area of the signed-in pages while the next page loads: a soft,
// blurred veil with the loading animation in the middle of the main area. The side menu
// and the top bar stay clear. loading-bar.js says when a page starts loading
// ("someless:navigate"); page-swap.js hides it again once the new content is in. The
// animation waits, paused, until it is needed.
(function () {
  var loader = document.getElementById("page-loader");
  if (!loader) return;
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

  // Start where the top bar ends (it scrolls away with the page); style.css keeps the
  // veil beside the side menu.
  function fitUnderTopBar() {
    var topbar = document.querySelector(".topbar");
    var top = topbar ? Math.max(0, topbar.getBoundingClientRect().bottom) : 0;
    loader.style.setProperty("--loader-top", top + "px");
  }

  function show() {
    fitUnderTopBar();
    loader.hidden = false;
    void loader.offsetWidth; // let the fade-in start from hidden
    loader.classList.add("is-visible");
    if (!animation) return;
    if (reduceMotion) animation.goToAndStop(Math.floor(animation.totalFrames / 2), true);
    else animation.play();
  }

  function hide() {
    loader.classList.remove("is-visible");
    if (animation) animation.pause();
    setTimeout(function () {
      if (!loader.classList.contains("is-visible")) loader.hidden = true;
    }, 300);
  }

  window.somelessPageLoader = { show: show, hide: hide };
  document.addEventListener("someless:navigate", show);

  // The Back button can bring a page back exactly as it was left, loader and all.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) hide();
  });
})();
