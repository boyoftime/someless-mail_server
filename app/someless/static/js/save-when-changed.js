// Save buttons that wait for a change: in a <form data-save-when-changed>, the submit button
// stays locked (and grey) until something in the form differs from how the page came, and
// locks again when it's changed back. Pages page-swap.js brings in are set up too.
(function () {
  function snapshot(form) {
    var parts = [];
    new FormData(form).forEach(function (value, name) {
      if (name !== "csrf_token") parts.push(name + "=" + value);
    });
    return parts.join("&");
  }

  function update(form) {
    var button = form.querySelector("button[type=submit]");
    if (!button || button.classList.contains("is-busy")) return;
    var unchanged = snapshot(form) === form.dataset.savedState;
    button.disabled = unchanged;
    button.classList.toggle("is-locked", unchanged);
  }

  function prepare(root) {
    root.querySelectorAll("form[data-save-when-changed]").forEach(function (form) {
      if (form.dataset.savedState !== undefined) return;
      form.dataset.savedState = snapshot(form);
      update(form);
    });
  }

  function changed(event) {
    var form = event.target.form || (event.target.closest && event.target.closest("form"));
    if (form && form.hasAttribute("data-save-when-changed") && form.dataset.savedState !== undefined) update(form);
  }

  document.addEventListener("input", changed);
  document.addEventListener("change", changed);
  // a dialog's Cancel puts a busy button back (busy-button.js): lock it again if nothing changed
  document.addEventListener("someless:done", function (event) {
    if (event.target.hasAttribute && event.target.hasAttribute("data-save-when-changed")) setTimeout(function () { update(event.target); }, 0);
  }, true);
  prepare(document);
  document.addEventListener("someless:swap", function (event) { prepare(event.detail.main); });
})();
