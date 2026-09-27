// Settings > Miscellaneous > Automatic domain checks. How often is greyed out (and out of reach)
// while the switch is off, but still sent with the form, so switching off keeps the interval.
// Custom opens a box for a number of hours or days, and under it the same time said the other
// way ("30 hours = 1 day and 6 hours"). Switching between Hours and Days keeps the time when
// it's whole days (48 hours = 2 days).
(function () {
  var form = document.querySelector("[data-checks-form]");
  if (!form) return;
  var on = form.querySelector("[data-checks-on]");
  var every = form.querySelector("[data-checks-every]");
  var custom = form.querySelector("[data-every-custom]");
  var row = form.querySelector("[data-custom-row]");
  var amount = form.querySelector("input[name=amount]");
  var hint = form.querySelector("[data-custom-hint]");
  var longest = hint.textContent;

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
  function describe(hours) {
    var days = Math.floor(hours / 24);
    var rest = hours % 24;
    return [days ? plural(days, "day") : "", rest ? plural(rest, "hour") : ""].filter(Boolean).join(" and ");
  }
  function unit() { return form.querySelector("input[name=unit]:checked").value; }

  function show() {
    every.inert = !on.checked; // not disabled: a disabled choice wouldn't be sent
    every.classList.toggle("is-off", !on.checked);
    row.hidden = !custom.checked;
    var n = /^\d+$/.test(amount.value.trim()) ? Number(amount.value.trim()) : 0;
    var hours = unit() === "days" ? n * 24 : n;
    if (!n) hint.textContent = longest;
    else if (unit() === "days") hint.textContent = "Every " + describe(hours) + " (" + plural(hours, "hour") + ").";
    else if (hours >= 24) hint.textContent = plural(hours, "hour") + " = " + describe(hours) + ".";
    else hint.textContent = "Every " + describe(hours) + ".";
    amount.placeholder = unit() === "days" ? "e.g. 3" : "e.g. 36";
  }

  form.querySelectorAll("input[name=unit]").forEach(function (input) {
    input.addEventListener("change", function () {
      var n = /^\d+$/.test(amount.value.trim()) ? Number(amount.value.trim()) : 0;
      if (n && input.value === "days" && n % 24 === 0) amount.value = n / 24; // 48 hours: 2 days
      else if (n && input.value === "hours") amount.value = n * 24;            // 2 days: 48 hours
      show();
    });
  });
  form.addEventListener("change", show);
  amount.addEventListener("input", show);
  custom.addEventListener("change", function () { if (custom.checked) amount.focus(); });
  show();
})();
