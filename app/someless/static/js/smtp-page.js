// SMTP & API page.
// - "Generate SMTP key" opens a dialog to name a key and choose its length and expiry. When
//   the server sends it back with a problem, it opens again by itself, keeping what was chosen.
// - A new key comes back in a dialog of its own, shown this once: when that dialog closes,
//   the key leaves the page.
// - The trash button asks first, in a dialog; "Delete" there sends the row's form.
// - The search box filters the keys as you type (Enter asks the server instead, which also
//   works without JavaScript).
// Dialogs close with Cancel, Escape or a click outside, fading away.
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

  function prepare(dialog) {
    if (!dialog || typeof dialog.showModal !== "function") return null;
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
    return dialog;
  }

  // Generate a key
  var generateDialog = prepare(document.getElementById("generate-dialog"));
  if (generateDialog) {
    document.querySelectorAll("[data-dialog-open='generate-dialog']").forEach(function (button) {
      button.addEventListener("click", function () { generateDialog.showModal(); });
    });
    if (generateDialog.hasAttribute("data-open")) {
      generateDialog.showModal();
      generateDialog.querySelector("input[name=name]").select();
    }
  }

  // The new key: shown once, then gone from the page
  var keyDialog = prepare(document.getElementById("key-dialog"));
  if (keyDialog) {
    keyDialog.addEventListener("close", function () { keyDialog.remove(); });
    keyDialog.showModal();
  }

  // Delete a key: ask first
  var deleteDialog = prepare(document.getElementById("delete-key-dialog"));
  var asking = null; // the row's form waiting for an answer
  if (deleteDialog) {
    document.querySelectorAll(".key-row .domain-delete").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (form.dataset.confirmed) return; // answered: on its way (page-swap.js)
        event.preventDefault();
        asking = form;
        deleteDialog.querySelector("[data-delete-name]").textContent = form.querySelector("[data-key-name]").dataset.keyName;
        deleteDialog.showModal(); // Cancel has the focus: Enter doesn't delete by accident
      });
    });
    deleteDialog.querySelector("[data-delete-confirm]").addEventListener("click", function () {
      if (!asking) return;
      asking.dataset.confirmed = "1";
      closeDialog(deleteDialog);
      asking.requestSubmit();
    });
  }

  // Search as you type
  var search = document.querySelector("[data-key-search] input");
  if (search) {
    var rows = document.querySelectorAll(".key-row");
    var none = document.querySelector(".key-table .domain-none");
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var match = row.dataset.keyName.indexOf(query) !== -1;
        row.hidden = !match;
        if (match) shown += 1;
      });
      none.hidden = shown > 0;
      none.querySelector("[data-search-text]").textContent = search.value.trim();
    });
  }
})();
