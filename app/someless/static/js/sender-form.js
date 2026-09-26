// Add or edit a sender: the phone beside the form shows the sender as an inbox will, filled in
// as you type (the first letter of the name in the round picture). While the address is at a
// domain that can't send (not one of the authenticated ones), the hint under it lights up.
(function () {
  var form = document.querySelector("[data-sender-form]");
  if (!form) return;
  var name = form.querySelector("input[name=name]");
  var email = form.querySelector("input[name=email]");
  var hint = form.querySelector("[data-domain-hint]");
  var domains = form.dataset.domains.split(" ");
  var shownName = document.querySelector("[data-preview-name]");
  var shownEmail = document.querySelector("[data-preview-email]");
  var initial = document.querySelector("[data-preview-initial]");

  function show() {
    var typedName = name.value.trim();
    var typedEmail = email.value.trim();
    shownName.textContent = typedName || name.placeholder;
    shownEmail.textContent = typedEmail || email.placeholder;
    initial.textContent = (typedName || name.placeholder).charAt(0).toUpperCase();
    var at = typedEmail.lastIndexOf("@");
    var domain = at === -1 ? "" : typedEmail.slice(at + 1).toLowerCase();
    // only once a domain is typed in full enough to judge (it has a dot and something after it)
    var judged = /\.[a-z]{2,}$/.test(domain);
    hint.classList.toggle("is-off", judged && domains.indexOf(domain) === -1);
  }

  name.addEventListener("input", show);
  email.addEventListener("input", show);
  show();
})();
