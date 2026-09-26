// Domains page.
// - "Add domain" opens a dialog to type one in. When the server sends it back with a
//   problem (already added, not a domain), it opens again by itself, keeping what was typed.
// - The trash button asks first, in a dialog; "Delete" there sends the row's form.
// - The search box filters the list as you type (Enter asks the server instead, which also
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

  // Add a domain
  var addDialog = prepare(document.getElementById("add-domain-dialog"));
  if (addDialog) {
    document.querySelectorAll("[data-dialog-open='add-domain-dialog']").forEach(function (button) {
      button.addEventListener("click", function () { addDialog.showModal(); });
    });
    if (addDialog.hasAttribute("data-open")) {
      addDialog.showModal();
      var input = addDialog.querySelector("input[name=name]");
      input.select();
    }
  }

  // Delete a domain: ask first
  var deleteDialog = prepare(document.getElementById("delete-domain-dialog"));
  var asking = null; // the row's form waiting for an answer
  if (deleteDialog) {
    document.querySelectorAll(".domain-delete").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (form.dataset.confirmed) return; // answered: on its way (page-swap.js)
        event.preventDefault();
        asking = form;
        deleteDialog.querySelector("[data-delete-name]").textContent = form.querySelector("[data-domain-name]").dataset.domainName;
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
  var search = document.querySelector("[data-domain-search] input");
  if (search) {
    var rows = document.querySelectorAll(".domain-row");
    var none = document.querySelector(".domain-none");
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var match = row.dataset.domain.indexOf(query) !== -1;
        row.hidden = !match;
        if (match) shown += 1;
      });
      none.hidden = shown > 0;
      none.querySelector("[data-search-text]").textContent = search.value.trim();
    });
  }
})();
