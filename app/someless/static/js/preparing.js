// The very first start: "Preparing your Someless Mail server". The mail animation plays and,
// every 2 seconds, the page asks how far the mail engine's setup got, ticking the steps off.
// Once it's done, the page fades out and goes on to where the admin was going (the welcome or
// the login page). When setting up takes unusually long (90 seconds), a link lets them go on
// without waiting: the SMTP & API page says what's left.
(function () {
  var main = document.querySelector(".preparing-main");
  if (!main) return;
  var SETUP_STEPS = ["new", "bootstrapped", "provisioned", "ready"]; // engine/setup.py
  var ASK_EVERY_MS = 2000;
  var OFFER_SKIP_AFTER_MS = 90000;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var holder = main.querySelector(".preparing-animation");
  if (window.lottie && holder) {
    var animation = window.lottie.loadAnimation({
      container: holder,
      renderer: "svg",
      loop: true,
      autoplay: !reduceMotion,
      path: holder.dataset.src,
    });
    if (reduceMotion) animation.addEventListener("DOMLoaded", function () { animation.goToAndStop(0, true); });
  }

  var steps = main.querySelectorAll(".preparing-step");
  function show(step) {
    var reached = SETUP_STEPS.indexOf(step);
    if (reached === -1) return;
    steps.forEach(function (item, index) {
      item.className = "preparing-step " + (index < reached ? "is-done" : index === reached ? "is-active" : "is-waiting");
    });
  }

  function finish() {
    show("ready");
    document.body.classList.add("is-ready"); // the last tick, then the page fades (style.css)
    setTimeout(function () { window.location.replace(main.dataset.next); }, reduceMotion ? 300 : 1300);
  }

  function ask() {
    fetch(main.dataset.progress, { credentials: "same-origin", cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (progress) {
        if (progress.ready) return finish();
        show(progress.step);
        setTimeout(ask, ASK_EVERY_MS);
      })
      .catch(function () { setTimeout(ask, ASK_EVERY_MS); }); // the panel just starting: ask again
  }
  setTimeout(ask, ASK_EVERY_MS);

  setTimeout(function () { main.querySelector(".preparing-skip").hidden = false; }, OFFER_SKIP_AFTER_MS);
})();
