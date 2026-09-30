// Mailboxes page.
// - "Create mailbox" and each mailbox's "Aliases" open their dialogs. When the server sends one
//   back with a problem (or right after an alias is added or deleted), it opens again by itself
//   (data-open), and the notice board comes down inside it.
// - "Configuration details" shows how a mail app connects, with the mailbox's address filled in.
// - The key and disk buttons open one shared dialog each, filled in for that mailbox.
// - The trash button asks first, in a dialog; "Delete mailbox" there sends the mailbox's form.
// - The password rules under a password get a tick the moment each is met. When they're changed
//   (Password rules, password-rules-dialog.js), both lists follow at once.
// - The search box filters the list as it's typed in, by address or alias.
// Dialogs close with Cancel, Escape or a click outside, fading away.
(function () {
  var main = document.getElementById("app-main") || document; // the page, not the side menu's dialog
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

  function focusFirst(dialog, selector) {
    var field = dialog.querySelector(selector);
    if (field) field.focus();
  }

  // The password rules, ticked off as the password is typed (the server checks the same ones)
  var tests = {
    letter: function (value) { return /[A-Za-z]/.test(value); },
    number: function (value) { return /[0-9]/.test(value); },
    special: function (value) { return /[^A-Za-z0-9]/.test(value); },
  };
  var lists = document.querySelectorAll("[data-password-rules][data-for]");
  lists.forEach(function (list) {
    var input = document.getElementById(list.dataset.for);
    if (!input) return;
    var check = function () {
      var minLength = Number(list.dataset.minLength) || 8;
      list.querySelectorAll("[data-rule]").forEach(function (item) {
        var rule = item.dataset.rule;
        var met = rule === "length" ? Array.from(input.value).length >= minLength : tests[rule](input.value);
        item.classList.toggle("is-met", met);
        item.querySelector(".rule-state").textContent = met ? " (done)" : " (not yet)";
      });
    };
    input.addEventListener("input", check);
    input.somelessCheck = check;
    check();
  });

  // New rules saved: the lists show them, ticked against what's typed now
  var rulesDialog = document.getElementById("mailbox-rules-dialog");
  if (rulesDialog) {
    rulesDialog.addEventListener("someless:password-rules", function (event) {
      var around = document.querySelector("dialog[open]:not([data-rules-picker])");   // the dialog it was opened from
      var rebuild = function () { lists.forEach(function (list) {
        list.dataset.minLength = event.detail.min_length;
        var ul = list.querySelector("ul");
        ul.replaceChildren.apply(ul, event.detail.rules.map(function (rule) {
          var item = document.createElement("li");
          item.dataset.rule = rule.key;
          item.innerHTML = '<span class="rule-mark" aria-hidden="true"></span><span class="visually-hidden rule-state"></span>';
          item.insertBefore(document.createTextNode(rule.label), item.lastChild);
          return item;
        }));
        var input = document.getElementById(list.dataset.for);
        if (input && input.somelessCheck) input.somelessCheck();
      }); };
      if (around && window.somelessResize) window.somelessResize(around, rebuild);   // glides to its new height
      else rebuild();
    });
  }

  function clearPasswords(dialog) {
    dialog.querySelectorAll("input[name=password], input[name=confirm]").forEach(function (input) {
      input.value = "";
      if (input.somelessCheck) input.somelessCheck();
    });
  }

  // Dialogs opened by a button of their own: Create mailbox, and each mailbox's Aliases
  main.querySelectorAll("dialog[id]:not([data-rules-picker])").forEach(function (dialog) {
    if (!prepare(dialog)) return;
    document.querySelectorAll("[data-dialog-open='" + dialog.id + "']").forEach(function (button) {
      button.addEventListener("click", function () {
        dialog.showModal();
        focusFirst(dialog, "input[name=local]");
      });
    });
  });

  // An alias dialog stays open after a change (?aliases=): the address loses that once it closes
  document.querySelectorAll("dialog[id^='aliases-dialog-']").forEach(function (dialog) {
    dialog.addEventListener("close", function () {
      if (location.search && history.replaceState) history.replaceState(history.state, "", location.pathname);
    });
  });

  // Configuration details, for the mailbox whose button was pressed
  var config = document.getElementById("config-dialog");
  if (config && typeof config.showModal === "function") {
    document.querySelectorAll("[data-config-email]").forEach(function (button) {
      button.addEventListener("click", function () {
        var email = button.dataset.configEmail;
        config.querySelectorAll("[data-config-name]").forEach(function (name) { name.textContent = email; });
        config.querySelector("[data-config-username]").textContent = email;
        config.querySelector("[data-config-copy]").dataset.copy = email;
        config.showModal();
      });
    });
  }

  // Change password and Edit storage: one dialog each, sent to the mailbox's own address
  function shared(dialogId, buttonAttr, fill) {
    var dialog = document.getElementById(dialogId);
    if (!dialog || typeof dialog.showModal !== "function") return;
    var form = dialog.querySelector("form");
    document.querySelectorAll("[" + buttonAttr + "]").forEach(function (button) {
      button.addEventListener("click", function () {
        form.action = button.dataset.url;
        dialog.querySelector("[data-dialog-email]").textContent = button.getAttribute(buttonAttr);
        fill(dialog, button);
        dialog.showModal();
      });
    });
  }
  shared("password-dialog", "data-password-for", function (dialog) {
    clearPasswords(dialog);
    setTimeout(function () { focusFirst(dialog, "input[name=password]"); }, 0);
  });
  shared("storage-dialog", "data-storage-for", function (dialog, button) {
    var size = dialog.querySelector("input[name=storage]");
    var unit = dialog.querySelector("select[name=unit]");
    size.value = button.dataset.size;
    unit.value = button.dataset.unit;
    unit.dispatchEvent(new Event("change")); // the dropdown shows it (dropdown.js)
    setTimeout(function () { size.select(); }, 0);
  });

  shared("sending-dialog", "data-sending-for", function (dialog, button) {
    var limit = dialog.querySelector("input[name=limit]");
    limit.value = button.dataset.limit;
    setTimeout(function () { limit.select(); }, 0);
  });

  // Delete a mailbox: ask first
  var deleteDialog = document.getElementById("delete-mailbox-dialog");
  var asking = null; // the mailbox's form waiting for an answer
  if (deleteDialog && typeof deleteDialog.showModal === "function") {
    document.querySelectorAll(".mailbox-delete").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (form.dataset.confirmed) return; // answered: on its way (page-swap.js)
        event.preventDefault();
        asking = form;
        deleteDialog.querySelector("[data-delete-name]").textContent = form.querySelector("[data-mailbox-email]").dataset.mailboxEmail;
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

  // Back from the server with a problem, or with an alias just added: open again, and bring the
  // board down inside the dialog (it came down behind it a moment ago)
  var reopen = main.querySelector("dialog[data-open]");
  if (reopen && typeof reopen.showModal === "function") {
    reopen.showModal();
    focusFirst(reopen, "input:not([type=hidden])");
    if (window.somelessBoard) window.somelessBoard.fromPage(main);
  }

  // Search as you type: by address or alias
  var search = main.querySelector("[data-mailbox-search] input");
  if (search) {
    var boxes = main.querySelectorAll(".mailbox-row");
    var none = main.querySelector(".mailbox-no-match");
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      var shown = 0;
      boxes.forEach(function (box) {
        var match = box.dataset.mailbox.indexOf(query) !== -1;
        box.hidden = !match;
        if (match) shown += 1;
      });
      none.hidden = shown > 0;
      none.querySelector("[data-search-text]").textContent = search.value.trim();
    });
  }
})();
