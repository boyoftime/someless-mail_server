// Settings page: as a new password is typed, each rule listed under it gets a tick the
// moment it is met. The server checks the same rules (PASSWORD_RULES in settings.py).
(function () {
  var input = document.getElementById("new-password");
  var list = document.querySelector("[data-password-rules]");
  if (!input || !list) return;

  var rules = {
    length: function (value) { return value.length >= 8; },
    mix: function (value) { return /[A-Za-z]/.test(value) && /[0-9]/.test(value); },
    special: function (value) { return /[^A-Za-z0-9]/.test(value); },
  };

  function check() {
    list.querySelectorAll("[data-rule]").forEach(function (item) {
      var met = rules[item.dataset.rule](input.value);
      item.classList.toggle("is-met", met);
      item.querySelector(".rule-state").textContent = met ? " (done)" : " (not yet)";
    });
  }

  input.addEventListener("input", check);
  check();
})();
