// Settings > Change password > "Password rules": a dialog to choose what a new password
// must contain. The minimum length sits on a glowing line of 12 dots, with a slider over
// it, so dragging, clicking and the arrow keys all work; three switches force special
// characters, numbers and letters. Save sends the choice to the server (page-swap.js
// brings the updated page in). Cancel, Escape or a click outside closes the dialog and
// forgets any changes.
(function () {
  var dialog = document.getElementById("password-rules-dialog");
  var opener = document.querySelector("[data-dialog-open='password-rules-dialog']");
  if (!dialog || !opener || typeof dialog.showModal !== "function") return;
  var form = dialog.querySelector("form");
  var picker = dialog.querySelector("[data-length-picker]");
  var range = picker.querySelector("input[type=range]");
  var shown = picker.querySelector("[data-length-value]");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function characters(n) {
    return n + (n === 1 ? " character" : " characters");
  }

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

  opener.addEventListener("click", function () {
    dialog.showModal();
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
  draw();
})();
