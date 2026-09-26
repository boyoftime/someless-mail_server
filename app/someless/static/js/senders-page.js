// Senders page.
// - The trash button asks first, in a dialog; "Delete" there sends the sender's form.
// - The search box filters the senders as you type, by name or address (Enter asks the
//   server instead, which also works without JavaScript).
// The dialog closes with Cancel, Escape or a click outside, fading away.
(function () {
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function closeDialog(dialog) {
    if (!dialog.open) return;
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

  // Delete a sender: ask first
  var dialog = document.getElementById("delete-sender-dialog");
  var asking = null; // the sender's form waiting for an answer
  if (dialog && typeof dialog.showModal === "function") {
    dialog.querySelectorAll("[data-dialog-close]").forEach(function (button) {
      button.addEventListener("click", function () { closeDialog(dialog); });
    });
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault(); // Escape: fade away like Cancel
      closeDialog(dialog);
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) closeDialog(dialog); // the dimmed page around it
    });
    document.querySelectorAll(".sender-delete").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (form.dataset.confirmed) return; // answered: on its way (page-swap.js)
        event.preventDefault();
        asking = form;
        dialog.querySelector("[data-delete-name]").textContent = form.querySelector("[data-sender-name]").dataset.senderName;
        dialog.showModal(); // Cancel has the focus: Enter doesn't delete by accident
      });
    });
    dialog.querySelector("[data-delete-confirm]").addEventListener("click", function () {
      if (!asking) return;
      asking.dataset.confirmed = "1";
      closeDialog(dialog);
      asking.requestSubmit();
    });
  }

  // Search as you type
  var search = document.querySelector("[data-sender-search] input");
  if (search) {
    var rows = document.querySelectorAll(".sender-row");
    var none = document.querySelector(".sender-none");
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var match = row.dataset.sender.indexOf(query) !== -1;
        row.hidden = !match;
        if (match) shown += 1;
      });
      none.hidden = shown > 0;
      none.querySelector("[data-search-text]").textContent = search.value.trim();
    });
  }
})();
