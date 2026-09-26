// Senders page.
// - The trash button asks first, in a dialog; "Delete" there sends the sender's form.
// - The search box filters the senders as you type, by name or address (Enter asks the
//   server instead, which also works without JavaScript).
// - "Send test email" opens a dialog that sends one through the mail engine, then follows it
//   every 2 seconds: delivered, bounced, trying again, or still on its way after a minute.
//   When the dialog closes, the sender's card shows the result.
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

  // A test email
  var testDialog = document.getElementById("test-dialog");
  if (testDialog && typeof testDialog.showModal === "function" && window.fetch) {
    var testForm = testDialog.querySelector("[data-test-form]");
    var line = testDialog.querySelector(".test-status");
    var testing = null; // the button of the sender being tested
    var polling = null;
    var sent = false;

    var show = function (text, state) {
      line.textContent = text;
      line.className = "test-status" + (state ? " is-" + state : "");
      line.hidden = !text;
    };
    var stop = function () {
      clearTimeout(polling);
      polling = null;
    };
    var ask = function (url, options) {
      return fetch(url, Object.assign({ credentials: "same-origin", headers: { Accept: "application/json" } }, options))
        .then(function (response) {
          return response.json().then(function (data) { return { ok: response.ok, data: data }; });
        });
    };
    var follow = function (url, tries) {
      polling = setTimeout(function () {
        ask(url).then(function (answer) {
          var found = answer.data;
          if (!answer.ok) return show(found.problem || "Couldn't follow the test email.", "bounced");
          if (found.status === "delivered") return show(found.detail || "Delivered", "delivered");
          if (found.status === "bounced") return show("Bounced: " + (found.detail || "the receiving server refused it"), "bounced");
          if (found.waited_long || tries >= 30) return show("Still on its way; the result will show on the card.", "retrying");
          if (found.status === "retrying") show("Trying again later: " + (found.detail || "the receiving server didn't take it yet"), "retrying");
          follow(url, tries + 1);
        }).catch(function () { follow(url, tries + 1); });
      }, 2000);
    };
    // the card's facts, as the server has them now (the last test included)
    var refreshCard = function (id) {
      fetch(location.href, { credentials: "same-origin" }).then(function (response) { return response.text(); }).then(function (html) {
        var selector = '.sender-row[data-sender-id="' + id + '"] .sender-facts';
        var fresh = new DOMParser().parseFromString(html, "text/html").querySelector(selector);
        var old = document.querySelector(selector);
        if (!fresh || !old) return;
        old.replaceWith(fresh);
        if (window.somelessLocalTime) window.somelessLocalTime(fresh);
      }).catch(function () {});
    };

    testDialog.querySelectorAll("[data-dialog-close]").forEach(function (button) {
      button.addEventListener("click", function () { closeDialog(testDialog); });
    });
    testDialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeDialog(testDialog);
    });
    testDialog.addEventListener("click", function (event) {
      if (event.target === testDialog) closeDialog(testDialog);
    });
    testDialog.addEventListener("close", function () {
      stop();
      if (sent && testing) refreshCard(testing.dataset.testSender);
      sent = false;
    });
    document.querySelectorAll("[data-test-sender]").forEach(function (button) {
      button.addEventListener("click", function () {
        testing = button;
        testDialog.querySelector("[data-test-from]").textContent = button.dataset.senderName;
        show("", "");
        testDialog.showModal();
        testForm.querySelector("[name=to]").focus();
      });
    });
    testForm.addEventListener("submit", function (event) {
      event.preventDefault(); // sent here, not as a page (page-swap.js)
      stop();
      var failed = function (problem) {
        show("", "");
        if (window.somelessBoard) window.somelessBoard.show({ type: "error", title: "Couldn't send the test", message: problem });
      };
      ask(testing.dataset.testUrl, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json",
                   "X-CSRFToken": testForm.querySelector("[name=csrf_token]").value },
        body: JSON.stringify({ to: testForm.elements.to.value, subject: testForm.elements.subject.value, text: testForm.elements.text.value }),
      }).then(function (answer) {
        testForm.dispatchEvent(new Event("someless:done")); // its button stops spinning (busy-button.js)
        if (!answer.ok || !answer.data.queue_id) return failed(answer.data.problem || "The panel didn't answer as expected.");
        sent = true;
        show("Queued. Waiting for the receiving server…", "queued");
        follow(testing.dataset.statusUrl.replace("QUEUE_ID", answer.data.queue_id), 0);
      }).catch(function () {
        testForm.dispatchEvent(new Event("someless:done"));
        failed("The panel didn't answer. Check your connection and try again.");
      });
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
