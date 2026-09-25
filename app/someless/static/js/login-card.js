// The login card: a welcome side with a Continue button, and the login form on the back.
// Flipping it sends a gust of wind ("someless:wind") through the background.
// Without JavaScript only the login form shows (see html:not(.js) in style.css).
(function () {
  var card = document.querySelector(".flip-card");
  if (!card) return;
  var front = card.querySelector(".face-front");
  var back = card.querySelector(".face-back");
  var continueButton = card.querySelector("[data-flip-to-login]");
  var backButton = card.querySelector("[data-flip-to-welcome]");
  var username = back.querySelector("input[name=username]");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var FLIP_MS = reduceMotion ? 0 : 900;

  // Only the side facing the visitor can be reached with the keyboard or a screen reader.
  function showSide(toLogin) {
    card.classList.toggle("is-flipped", toLogin);
    front.inert = toLogin;
    back.inert = !toLogin;
  }

  function flip(toLogin) {
    showSide(toLogin);
    if (!reduceMotion) {
      card.classList.remove("is-flipping");
      void card.offsetWidth; // restart the sway animation
      card.classList.add("is-flipping");
      setTimeout(function () {
        card.classList.remove("is-flipping");
      }, FLIP_MS);
      document.dispatchEvent(new CustomEvent("someless:wind"));
    }
    setTimeout(function () {
      (toLogin ? username : continueButton).focus({ preventScroll: true });
    }, FLIP_MS / 2);
  }

  showSide(card.classList.contains("is-flipped"));
  backButton.hidden = false;
  continueButton.addEventListener("click", function () { flip(true); });
  backButton.addEventListener("click", function () { flip(false); });
})();
