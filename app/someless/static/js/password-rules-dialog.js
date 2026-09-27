// "Password rules" (Settings > Change password, and the mailbox dialogs on Mailboxes): a dialog
// to choose what a new password must contain. The minimum length sits on a glowing line of 12
// dots, with a slider over it, so dragging, clicking and the arrow keys all work; three switches
// force special characters, numbers and letters. Cancel, Escape or a click outside closes the
// dialog and forgets any changes.
// Save sends the choice to the server: page-swap.js brings the updated page in; or, for a form
// marked data-save-in-place (opened from another dialog), it's sent in the background, the
// dialog closes, and the dialog tells the page ("someless:password-rules", with the new rules).
(function () {
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function characters(n) {
    return n + (n === 1 ? " character" : " characters");
  }

  function setUp(dialog) {
    var openers = document.querySelectorAll("[data-dialog-open='" + dialog.id + "']");
    if (!openers.length || typeof dialog.showModal !== "function") return;
    var form = dialog.querySelector("form");
    var picker = dialog.querySelector("[data-length-picker]");
    var range = picker.querySelector("input[type=range]");
    var shown = picker.querySelector("[data-length-value]");

    // Light the line, its dots and the numbers up to the chosen length.
    function draw() {
      var n = Number(range.value);
      picker.style.setProperty("--value", n);
      shown.textContent = characters(n);
      range.setAttribute("aria-valuetext", characters(n));
      picker.querySelectorAll("[data-n]").forEach(function (el) {
        var at = Number(el.dataset.n);
        el.classList.toggle("is-lit", at <= n);
        el.classList.toggle("is-current", at === n);
      });
    }

    function close() {
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

    // Closed without saving: back to the saved rules.
    function cancel() {
      form.reset();
      draw();
      close();
    }

    openers.forEach(function (opener) {
      opener.addEventListener("click", function () {
        dialog.showModal();
      });
    });
    range.addEventListener("input", draw);
    // The numbers under the line pick a length too.
    picker.querySelectorAll(".length-numbers [data-n]").forEach(function (number) {
      number.addEventListener("click", function () {
        range.value = number.dataset.n;
        draw();
        range.focus();
      });
    });
    dialog.querySelector("[data-dialog-close]").addEventListener("click", cancel);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault(); // Escape: close the same gentle way as Cancel
      cancel();
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) cancel(); // the dimmed page around it
    });

    if (form.hasAttribute("data-save-in-place") && window.fetch) {
      var board = function (options) {
        if (window.somelessBoard) window.somelessBoard.show(options);
      };
      form.addEventListener("submit", function (event) {
        event.preventDefault(); // not as a page (page-swap.js): the dialog underneath stays as it is
        fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin",
                             headers: { Accept: "application/json" } })
          .then(function (response) {
            return response.json().then(function (data) { return { ok: response.ok, data: data }; });
          })
          .then(function (answer) {
            form.dispatchEvent(new Event("someless:done")); // its button stops spinning (busy-button.js)
            if (!answer.ok) {
              board({ type: "error", title: "Couldn't save the rules", message: answer.data.problem || "Try again." });
              return;
            }
            // what was saved is what Cancel goes back to from now on
            range.defaultValue = range.value;
            form.querySelectorAll("input[type=checkbox]").forEach(function (box) { box.defaultChecked = box.checked; });
            dialog.dispatchEvent(new CustomEvent("someless:password-rules", { detail: answer.data }));
            close();
            // on the dialog underneath, once this one has gone
            setTimeout(function () { board({ type: "success", title: "Saved", message: answer.data.message }); }, 200);
          })
          .catch(function () {
            form.dispatchEvent(new Event("someless:done"));
            board({ type: "error", title: "Couldn't save the rules", message: "The panel didn't answer. Check your connection and try again." });
          });
      });
    }
    draw();
  }

  document.querySelectorAll("dialog[data-rules-picker]").forEach(setUp);
})();
