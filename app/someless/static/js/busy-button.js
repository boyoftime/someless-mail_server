// Submit buttons with data-busy-label show a spinner and a busy label while their form
// is being sent, and lock so a double click can't send it twice.
// A script that sends the form in the background fires "someless:done" on the form
// when it has an answer, which puts the button back to normal.
(function () {
  document.querySelectorAll("button[data-busy-label]").forEach(function (button) {
    var form = button.form;
    if (!form) return;
    var label = button.querySelector(".button-label");
    var idleText = label ? label.textContent : "";

    function reset() {
      button.classList.remove("is-busy");
      button.removeAttribute("aria-busy");
      button.disabled = false;
      if (label) label.textContent = idleText;
    }

    form.addEventListener("submit", function () {
      button.classList.add("is-busy");
      button.setAttribute("aria-busy", "true");
      if (label) label.textContent = button.dataset.busyLabel;
      // Lock after the browser has taken this submit, so the form still sends.
      setTimeout(function () {
        button.disabled = true;
      }, 0);
    });

    form.addEventListener("someless:done", reset);

    // Coming back with the Back button can show the page from cache, still busy.
    window.addEventListener("pageshow", function (event) {
      if (event.persisted) reset();
    });
  });
})();
