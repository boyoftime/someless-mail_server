// Disabling a sender or a mailbox (disable-dialog.html), on the Senders and Mailboxes pages: a
// Disable button ([data-disable-url]) opens the dialog for its sender or mailbox, its own name in
// it, and what's said of a mailbox (with Refuse new mail, off to start) only when there is one.
// The dialog closes with Cancel, Escape or a click outside, fading away. Enabling needs no asking:
// it's a plain button in a form. Without JavaScript the dialog isn't there to ask.
(function () {
  var dialog = document.getElementById("disable-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var form = dialog.querySelector("form");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function close() {
    if (!dialog.open) return;
    if (reduceMotion) return dialog.close();
    dialog.classList.add("is-closing");
    setTimeout(function () {
      dialog.classList.remove("is-closing");
      dialog.close();
    }, 180);
  }

  document.querySelectorAll("[data-disable-url]").forEach(function (button) {
    button.addEventListener("click", function () {
      form.action = button.dataset.disableUrl;
      dialog.querySelector("[data-disable-name]").textContent = button.dataset.disableName;
      var mailbox = button.dataset.disableMailbox === "1";
      dialog.querySelectorAll("[data-only-mailbox]").forEach(function (part) { part.hidden = !mailbox; });
      form.querySelector("input[name=refuse]").checked = false;
      dialog.showModal();   // (Cancel has the focus: Enter doesn't disable by accident)
    });
  });
  dialog.querySelector("[data-dialog-close]").addEventListener("click", close);
  dialog.addEventListener("cancel", function (event) {
    event.preventDefault();   // Escape: fade away like Cancel
    close();
  });
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) close();   // the dimmed page around it
  });
})();
