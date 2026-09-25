// Notice board: hangs from two ropes, drops in from the top of the screen with a swing,
// stays up for 3 seconds (paused while the pointer is on it), then is pulled back up.
// A click sends it back up straight away. Green glow for success, red glow for errors.
//
//   somelessBoard.show({ type: "error", title: "Couldn't log you in", message: "..." })
//
// Server messages marked data-board (see shell.html) are shown this way on page load.
(function () {
  var STAY_MS = 3000;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var ICONS = {
    success: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.2 4.2L19 7"/></svg>',
    error: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M12 6.5v7"/><path d="M12 17.5h.01"/></svg>',
  };

  var wrap, icon, title, message, politeNews, urgentNews, timer;

  function build() {
    wrap = document.createElement("div");
    wrap.className = "board-wrap";
    wrap.setAttribute("aria-hidden", "true"); // read out through the live regions below
    wrap.innerHTML =
      '<span class="board-rope board-rope-left"></span>' +
      '<span class="board-rope board-rope-right"></span>' +
      '<div class="board">' +
      '<span class="board-ring board-ring-left"></span>' +
      '<span class="board-ring board-ring-right"></span>' +
      '<div class="board-icon"></div>' +
      '<div class="board-text"><p class="board-title"></p><p class="board-message"></p></div>' +
      "</div>";
    document.body.appendChild(wrap);
    icon = wrap.querySelector(".board-icon");
    title = wrap.querySelector(".board-title");
    message = wrap.querySelector(".board-message");

    // Screen readers: errors interrupt, success waits its turn.
    politeNews = liveRegion("polite");
    urgentNews = liveRegion("assertive");

    wrap.addEventListener("mouseenter", function () { clearTimeout(timer); });
    wrap.addEventListener("mouseleave", function () {
      if (wrap.classList.contains("is-down")) timer = setTimeout(hide, 1200);
    });
    wrap.addEventListener("click", hide);
  }

  function liveRegion(politeness) {
    var region = document.createElement("div");
    region.className = "visually-hidden";
    region.setAttribute("aria-live", politeness);
    region.setAttribute("aria-atomic", "true");
    document.body.appendChild(region);
    return region;
  }

  function hide() {
    clearTimeout(timer);
    if (!wrap || !wrap.classList.contains("is-down")) return;
    wrap.classList.remove("is-down");
    wrap.classList.add("is-up");
  }

  function show(options) {
    if (!wrap) build();
    clearTimeout(timer);
    var type = options.type === "error" ? "error" : "success";
    wrap.dataset.type = type;
    icon.innerHTML = ICONS[type];
    title.textContent = options.title || "";
    message.textContent = options.message || "";
    var news = type === "error" ? urgentNews : politeNews;
    news.textContent = "";
    setTimeout(function () { news.textContent = (options.title || "") + ". " + (options.message || ""); }, 50);

    wrap.classList.remove("is-up", "is-down");
    void wrap.offsetWidth; // restart the drop animation
    wrap.classList.add("is-down");
    timer = setTimeout(hide, STAY_MS + (reduceMotion ? 0 : 900));
  }

  // Messages from the server (e.g. "Password changed.") come down on a board too. Error
  // messages also stay next to their form after the board goes back up. page-swap.js
  // calls this for each page it brings in without a reload.
  function fromPage(root) {
    var first = root.querySelector("[data-board]");
    if (!first) return;
    root.querySelectorAll("[data-board]").forEach(function (el) {
      if (el.dataset.board !== "error") el.hidden = true;
    });
    show({ type: first.dataset.board, title: first.dataset.boardTitle, message: first.textContent.trim() });
  }

  window.somelessBoard = { show: show, hide: hide, fromPage: fromPage };
  fromPage(document);
})();
