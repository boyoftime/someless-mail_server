// Need help? on a domain's Authenticate page: a dialog that makes links to share the domain's
// records (help_links.py). Everything happens in the dialog, without leaving the page:
// - "Ask for a password" shows the password field; "Create link" makes the link, and the list
//   shows it with a copy button, this once.
// - The list says how far each link got (not opened yet, opened, authenticated, expired): asked
//   again each time the dialog opens. The trash button deletes a link.
// Close, Escape or a click outside closes it, fading away.
(function () {
  var dialog = document.getElementById("help-dialog");
  if (!dialog || typeof dialog.showModal !== "function" || !window.fetch) return;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var list = dialog.querySelector("[data-help-list]");
  var create = dialog.querySelector("[data-help-create]");
  var passwordOn = create.querySelector("[data-help-password-on]");
  var passwordField = create.querySelector("[data-help-password]");

  function close() {
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

  function board(type, title, message) {
    if (window.somelessBoard) window.somelessBoard.show({ type: type, title: title, message: message });
  }

  function ask(url, options) {
    return fetch(url, Object.assign({ credentials: "same-origin", headers: { Accept: "application/json" } }, options || {}))
      .then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      });
  }

  function send(form) {
    return ask(form.action, { method: "POST", body: new FormData(form) });
  }

  function show(html) {
    list.innerHTML = html;
  }

  function refresh() {
    ask(dialog.dataset.listUrl).then(function (answer) {
      if (answer.ok) show(answer.data.html);
    }).catch(function () {});
  }

  dialog.querySelectorAll("[data-dialog-close]").forEach(function (button) {
    button.addEventListener("click", close);
  });
  dialog.addEventListener("cancel", function (event) {
    event.preventDefault(); // Escape: fade away like Close
    close();
  });
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) close(); // the dimmed page around it
  });
  document.querySelectorAll("[data-dialog-open='help-dialog']").forEach(function (button) {
    button.addEventListener("click", function () {
      dialog.showModal();
      refresh();
    });
  });

  passwordOn.addEventListener("change", function () {
    passwordField.hidden = !passwordOn.checked;
    if (passwordOn.checked) passwordField.querySelector("input").focus();
  });

  create.addEventListener("submit", function (event) {
    event.preventDefault(); // made here, not as a page (page-swap.js)
    send(create).then(function (answer) {
      create.dispatchEvent(new Event("someless:done")); // its button stops spinning (busy-button.js)
      if (!answer.ok) return board("error", "Couldn't make the link", answer.data.problem || "Try again.");
      show(answer.data.html);
      passwordField.querySelector("input").value = "";
      board("success", "Link made", "Copy it and send it: it's shown only this once.");
      var copy = list.querySelector(".copy-box");
      if (copy) copy.scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
    }).catch(function () {
      create.dispatchEvent(new Event("someless:done"));
      board("error", "Couldn't make the link", "The panel didn't answer. Check your connection and try again.");
    });
  });

  // Delete a link: the list comes back without it
  list.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-help-delete]");
    if (!form) return;
    event.preventDefault();
    send(form).then(function (answer) {
      if (answer.ok) show(answer.data.html);
    }).catch(function () {
      board("error", "Couldn't delete the link", "The panel didn't answer. Check your connection and try again.");
    });
  });
})();
