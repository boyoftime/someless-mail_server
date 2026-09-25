// The eye button next to a password field shows or hides what was typed.
// The button stays hidden without JavaScript, since it couldn't work.
(function () {
  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;
    button.hidden = false;

    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", String(show));
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      input.focus();
    });

    // Always send the field as a password field, so browsers treat it as one.
    if (input.form) {
      input.form.addEventListener("submit", function () {
        input.type = "password";
      });
    }
  });
})();
