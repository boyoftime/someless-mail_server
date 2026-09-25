// Cards that open and close when their header is clicked (the settings cards). They start
// closed, unless the server opened one to show an error. style.css unfolds them smoothly;
// a card glows brighter while open, and each click sends a pulse of light around it.
// While closed, a card's form can't be reached with the keyboard.
(function () {
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  document.querySelectorAll("[data-card-toggle]").forEach(function (toggle) {
    var card = toggle.closest("[data-card]");
    var body = document.getElementById(toggle.getAttribute("aria-controls"));
    if (!card || !body) return;

    function show(open) {
      card.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      body.inert = !open;
    }

    function pulse() {
      if (reduceMotion) return;
      card.classList.remove("is-flaring");
      void card.offsetWidth; // restart the pulse on quick repeated clicks
      card.classList.add("is-flaring");
    }

    toggle.addEventListener("click", function () {
      show(toggle.getAttribute("aria-expanded") !== "true");
      pulse();
    });
    card.addEventListener("animationend", function (event) {
      if (event.animationName === "card-flare") card.classList.remove("is-flaring");
    });
    show(toggle.getAttribute("aria-expanded") === "true");
  });
})();
