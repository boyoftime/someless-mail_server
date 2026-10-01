// The API guide (api-docs.html), as in Postman: each call's request shows in the language picked,
// the same for every call. Picking one (a click, or the arrow keys, Home and End) slides the
// highlight over to it and fades the code across, in every call at once, without the call being
// read moving on the screen; the browser remembers it for the next visit. The copy button beside
// the tabs copies the request in that language. A call picked in the index at the top (page-swap.js
// glides there) lights up for a moment. Without JavaScript, every language shows, one under another.
(function () {
  var consoles = Array.from(document.querySelectorAll(".api-console.is-request"));
  if (!consoles.length) return;
  var STORED = "someless-api-language";
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function glide(box) {   // the highlight under the language picked
    var tabs = box.querySelector(".api-langs");
    var on = tabs.querySelector("[aria-selected='true']");
    var glider = tabs.querySelector(".api-langs-glider");
    if (!on || !on.offsetWidth) return;
    glider.style.width = on.offsetWidth + "px";
    glider.style.transform = "translateX(" + on.offsetLeft + "px)";
    tabs.classList.add("is-placed");   // (from now on it slides)
  }

  function show(box, language, animate) {
    var codes = box.querySelector(".api-codes");
    var next = codes.querySelector("[data-api-code='" + language + "']");
    if (!next) return;
    var before = codes.offsetHeight;
    codes.querySelectorAll("[data-api-code]").forEach(function (code) { code.hidden = code !== next; });
    box.querySelectorAll("[data-api-lang]").forEach(function (tab) {
      var on = tab.dataset.apiLang === language;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
    });
    box.querySelector(".api-copy").dataset.copy = next.dataset.code;
    glide(box);
    if (!animate || reduceMotion) return;
    next.classList.remove("is-entering");
    void next.offsetWidth;   // (to play again)
    next.classList.add("is-entering");
    var after = codes.offsetHeight;
    if (after === before) return;
    codes.style.height = before + "px";   // the console grows or shrinks to the new code
    void codes.offsetHeight;
    codes.style.height = after + "px";
    clearTimeout(codes.settled);
    codes.settled = setTimeout(function () { codes.style.height = ""; }, 340);
  }

  function choose(language, from) {
    // The call being read stays where it is on the screen, though the ones above it change height
    var anchor = from ? from.closest(".api-call") : null;
    var top = anchor ? anchor.getBoundingClientRect().top : 0;
    consoles.forEach(function (box) { show(box, language, box === (from && from.closest(".api-console"))); });
    if (anchor) window.scrollBy(0, anchor.getBoundingClientRect().top - top);
    try {
      localStorage.setItem(STORED, language);
    } catch (error) { /* not remembered, that's all */ }
  }

  consoles.forEach(function (box) {
    var tabs = Array.from(box.querySelectorAll("[data-api-lang]"));
    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () { choose(tab.dataset.apiLang, tab); });
      tab.addEventListener("keydown", function (event) {
        var to = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[event.key];
        if (to === undefined) return;
        event.preventDefault();
        var next = tabs[(to + tabs.length) % tabs.length];
        choose(next.dataset.apiLang, next);
        next.focus();
      });
    });
  });

  var remembered = null;
  try {
    remembered = localStorage.getItem(STORED);
  } catch (error) { /* no storage (private window): cURL first */ }
  var first = consoles[0].querySelector("[data-api-lang='" + remembered + "']") ? remembered : "curl";
  consoles.forEach(function (box) { show(box, first, false); });
  // the highlight again once the font is in, and when the page's width changes
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { consoles.forEach(glide); });
  window.addEventListener("resize", function () { consoles.forEach(glide); });

  // Get help from AI: the button at the top right flashes, and its card pops up over the page,
  // blurred behind it. It closes with Close, Escape or a click outside, fading away.
  var aiDialog = document.getElementById("ai-dialog");
  var aiButton = document.querySelector("[data-dialog-open='ai-dialog']");
  if (aiDialog && aiButton && typeof aiDialog.showModal === "function") {
    var closeAi = function () {
      if (!aiDialog.open) return;
      if (reduceMotion) return aiDialog.close();
      aiDialog.classList.add("is-closing");
      setTimeout(function () {
        aiDialog.classList.remove("is-closing");
        aiDialog.close();
      }, 200);
    };
    aiButton.addEventListener("click", function () {
      aiButton.classList.remove("is-flashing");
      void aiButton.offsetWidth;   // (to flash again)
      aiButton.classList.add("is-flashing");
      aiDialog.showModal();
    });
    aiButton.addEventListener("animationend", function () { aiButton.classList.remove("is-flashing"); });
    aiDialog.querySelector("[data-dialog-close]").addEventListener("click", closeAi);
    aiDialog.addEventListener("cancel", function (event) {
      event.preventDefault();   // Escape: fade away like Close
      closeAi();
    });
    aiDialog.addEventListener("click", function (event) {
      if (event.target === aiDialog) closeAi();   // the blurred page around it
    });
  }

  // The index: the call glided to lights up as it arrives
  function flash(call) {
    if (!call) return;
    call.classList.remove("is-flash");
    void call.offsetWidth;
    call.classList.add("is-flash");
  }
  document.querySelectorAll(".api-index-link").forEach(function (link) {
    link.addEventListener("click", function () {
      var call = document.getElementById(link.hash.slice(1));
      setTimeout(function () { flash(call); }, reduceMotion ? 0 : 420);
    });
  });
  if (location.hash) flash(document.getElementById(location.hash.slice(1)));
})();
