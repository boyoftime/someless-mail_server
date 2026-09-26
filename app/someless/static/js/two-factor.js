// Settings > Two-factor authentication. With the PIN on, flipping its switch doesn't turn
// it off straight away: the form below slides open and asks for a PIN from the app first
// ("Keep it on" closes it again). PIN boxes keep to digits. Without JavaScript that form
// is simply always there.
(function () {
  document.querySelectorAll("[data-reveal]").forEach(function (button) {
    var panel = document.getElementById(button.getAttribute("aria-controls"));
    if (!panel) return;
    var input = panel.querySelector("input[name=pin]");

    function show(open) {
      panel.classList.toggle("is-open", open);
      button.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && input) input.focus();
    }

    button.addEventListener("click", function () {
      show(button.getAttribute("aria-expanded") !== "true");
    });
    panel.querySelectorAll("[data-reveal-close]").forEach(function (close) {
      close.addEventListener("click", function () {
        show(false);
        button.focus();
      });
    });
  });

  document.querySelectorAll(".factor-form .pin-input").forEach(function (input) {
    input.addEventListener("input", function () {
      var digits = input.value.replace(/\D/g, "").slice(0, 6);
      if (input.value !== digits) input.value = digits;
    });
  });
})();
