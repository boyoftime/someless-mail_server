// Cards that open and close when their header is clicked (the settings cards). They start
// closed, unless the server opened one to show an error. style.css unfolds them smoothly;
// a card glows brighter while open, and each click sends a pulse of light around it.
// While closed, a card's form can't be reached with the keyboard. A card that opens past the
// bottom of the screen brings itself into view as it unfolds, its top first.
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

    // Opening past the bottom of the screen: the page glides up just enough to show the whole
    // card, but never past its top (a tall card shows from its start, the rest by scrolling).
    function bringIntoView() {
      var bar = document.querySelector(".topbar");
      var stuck = bar && /sticky|fixed/.test(getComputedStyle(bar).position) ? bar.offsetHeight : 0;
      var room = 16 + stuck;
      var top = card.getBoundingClientRect().top;
      var clip = body.firstElementChild || body;   // still folded: its clip knows the full height
      var bottom = top + card.offsetHeight - body.offsetHeight + clip.scrollHeight;   // once unfolded
      var below = bottom + 16 - window.innerHeight;
      if (below <= 0) return;
      var distance = Math.min(below, top - room);
      // in step with the unfolding: at the page's end there's no room to glide into until the
      // card has grown, so each frame goes as far as the page lets it
      var start = window.scrollY;
      var began = performance.now();
      var lasts = reduceMotion ? 0 : 520;
      (function step(now) {
        var done = lasts ? Math.min(1, (now - began) / lasts) : 1;
        window.scrollTo(0, start + distance * (1 - Math.pow(1 - done, 3)));
        if (done < 1) requestAnimationFrame(step);
      })(began);
    }

    toggle.addEventListener("click", function () {
      var opening = toggle.getAttribute("aria-expanded") !== "true";
      show(opening);
      pulse();
      if (opening) bringIntoView();
    });
    card.addEventListener("animationend", function (event) {
      if (event.animationName === "card-flare") card.classList.remove("is-flaring");
    });
    show(toggle.getAttribute("aria-expanded") === "true");
  });
})();
