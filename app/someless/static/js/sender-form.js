// Add or edit a sender: the phone beside the form shows the sender as an inbox will, filled in
// as you type (the first letter of the name in the round picture). The address comes in two
// parts: what's typed before the @, and the domain picked from the list (only authenticated
// ones). Typing or pasting a whole address picks its domain from the list, when it's there.
(function () {
  var form = document.querySelector("[data-sender-form]");
  if (!form) return;
  var name = form.querySelector("input[name=name]");
  var local = form.querySelector("input[name=local]");
  var domain = form.querySelector("select[name=domain]");
  var shownName = document.querySelector("[data-preview-name]");
  var shownEmail = document.querySelector("[data-preview-email]");
  var initial = document.querySelector("[data-preview-initial]");

  function show() {
    var typedName = name.value.trim();
    shownName.textContent = typedName || name.placeholder;
    shownEmail.textContent = (local.value.trim() || local.placeholder) + "@" + domain.value;
    initial.textContent = (typedName || name.placeholder).charAt(0).toUpperCase();
  }

  // no-reply@cloudnix.net typed or pasted: no-reply here, @cloudnix.net picked in the list
  function pickTypedDomain() {
    var at = local.value.indexOf("@");
    if (at === -1) return;
    var typed = local.value.slice(at + 1).trim().toLowerCase();
    var match = Array.prototype.some.call(domain.options, function (option) { return option.value === typed; });
    if (!match) return;
    local.value = local.value.slice(0, at);
    domain.value = typed;
    domain.dispatchEvent(new Event("change", { bubbles: true })); // the dropdown shows it (dropdown.js)
  }

  name.addEventListener("input", show);
  local.addEventListener("input", function () {
    pickTypedDomain();
    show();
  });
  domain.addEventListener("change", show);
  show();
})();
