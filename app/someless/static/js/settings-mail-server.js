// Settings > Mail server name. Choosing another name asks first, in a dialog, because apps,
// the proxy host and the reverse DNS must follow it; "Switch" there sends the form. Saving
// the name already in use sends it straight away. The dialog closes with Cancel, Escape or
// a click outside, fading away.
(function () {
  var form = document.querySelector("[data-server-name-form]");
  var dialog = document.getElementById("server-name-dialog");
  if (!form || !dialog || typeof dialog.showModal !== "function") return;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function closeDialog() {
    if (!dialog.open) return;
    form.dispatchEvent(new Event("someless:done")); // its Save button stops spinning (busy-button.js)
    if (reduceMotion) {
      dialog.close();
      return;
    }
    dialog.classList.add("is-closing");
    setTimeout(function () {
      dialog.classList.remove("is-closing");
      dialog.close();
    }, 180);
  }

  dialog.querySelectorAll("[data-dialog-close]").forEach(function (button) {
    button.addEventListener("click", closeDialog);
  });
  dialog.addEventListener("cancel", function (event) {
    event.preventDefault(); // Escape: fade away like Cancel
    closeDialog();
  });
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) closeDialog(); // the dimmed page around it
  });

  form.addEventListener("submit", function (event) {
    if (form.dataset.confirmed) return; // answered: on its way (page-swap.js)
    var chosen = form.querySelector("input[name=server_name]:checked");
    if (!chosen || chosen.value === form.dataset.current) return;
    event.preventDefault();
    dialog.querySelectorAll("[data-new-name]").forEach(function (el) { el.textContent = chosen.value; });
    dialog.showModal(); // Cancel has the focus: Enter doesn't switch by accident
  });

  dialog.querySelector("[data-switch-confirm]").addEventListener("click", function () {
    form.dataset.confirmed = "1";
    dialog.close();
    form.requestSubmit();
  });
})();
