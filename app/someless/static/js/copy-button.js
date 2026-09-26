// Buttons that copy a piece of text (data-copy), such as the two-factor key. The copy icon
// turns into a tick that draws itself and "Copied" pops up for a moment. Works on a plain
// http:// address too, where browsers don't allow the modern clipboard.
(function () {
  var news = null; // read out by screen readers

  function announce(text) {
    if (!news) {
      news = document.createElement("div");
      news.className = "visually-hidden";
      news.setAttribute("aria-live", "polite");
      document.body.appendChild(news);
    }
    news.textContent = "";
    setTimeout(function () { news.textContent = text; }, 50);
  }

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    // http://: the older way, through a hidden text box
    return new Promise(function (resolve, reject) {
      var box = document.createElement("textarea");
      box.value = text;
      box.setAttribute("readonly", "");
      box.style.cssText = "position: fixed; top: 0; left: 0; opacity: 0; pointer-events: none;";
      document.body.appendChild(box);
      box.select();
      var copied = false;
      try {
        copied = document.execCommand("copy");
      } catch (error) {
        // not allowed: reported below
      }
      box.remove();
      if (copied) resolve();
      else reject(new Error("copy refused"));
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    copy(button.dataset.copy).then(function () {
      button.classList.remove("is-copied");
      void button.offsetWidth; // play the tick again on a second click
      button.classList.add("is-copied");
      clearTimeout(button.copiedTimer);
      button.copiedTimer = setTimeout(function () { button.classList.remove("is-copied"); }, 1800);
      announce("Copied");
    }, function () {
      if (window.somelessBoard) {
        window.somelessBoard.show({ type: "error", title: "Couldn't copy", message: "Select the text and copy it yourself." });
      }
    });
    button.focus(); // the hidden text box took the focus for a moment
  });
})();
