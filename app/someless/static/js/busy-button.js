// Submit buttons with data-busy-label show a spinner and a busy label while their form
// is being sent, and lock so a double click can't send it twice. This covers every such
// button, those on pages page-swap.js brings in later included.
// A script that sends a form in the background fires "someless:done" on the form when the
// form is still there after the answer (a wrong password, say), which puts the button back
// to normal.
(function () {
  function buttonOf(form) {
    return form instanceof HTMLFormElement ? form.querySelector("button[data-busy-label]") : null;
  }

  function busy(button) {
    var label = button.querySelector(".button-label");
    if (label && !button.dataset.idleLabel) button.dataset.idleLabel = label.textContent;
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    if (label) label.textContent = button.dataset.busyLabel;
    // Lock after the browser has taken this submit, so the form still sends.
    setTimeout(function () {
      button.disabled = true;
    }, 0);
  }

  function reset(button) {
    var label = button.querySelector(".button-label");
    button.classList.remove("is-busy");
    button.removeAttribute("aria-busy");
    button.disabled = false;
    if (label && button.dataset.idleLabel) label.textContent = button.dataset.idleLabel;
  }

  document.addEventListener("submit", function (event) {
    var button = buttonOf(event.target);
    if (button) busy(button);
  });

  // "someless:done" doesn't bubble, so it is caught on its way down to the form.
  document.addEventListener("someless:done", function (event) {
    var button = buttonOf(event.target);
    if (button) reset(button);
  }, true);

  // Coming back with the Back button can show the page from cache, still busy.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) document.querySelectorAll("button[data-busy-label].is-busy").forEach(reset);
  });
})();
