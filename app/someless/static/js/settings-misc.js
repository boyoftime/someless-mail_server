// Settings > Miscellaneous.
// - The Minutes / Hours / Days switches (automatic domain checks, the webmail sign-in lock): the
//   highlight glides over to the one chosen.
// - Automatic domain checks: How often is greyed out (and out of reach) while the switch is off,
//   but still sent with the form, so switching off keeps the interval. Custom opens a box for a
//   number of minutes, hours or days, and under it the same time said in words ("90 minutes =
//   1 hour and 30 minutes"). Switching the unit keeps the time when it's whole in the new one
//   (120 minutes = 2 hours; 2 days = 2880 minutes).
// - Webmail sign-in lock: how many and how long are greyed out the same way while it's off.
(function () {
  var PER = { minutes: 1, hours: 60, days: 1440 };
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // The glide: one highlight behind the switch's words, moved to the chosen one
  function glide(group, at_once) {
    var glider = group.querySelector(".unit-switch-glider");
    var chosen = group.querySelector("input:checked + span");
    if (!glider || !chosen || !chosen.offsetWidth) return;
    group.classList.toggle("is-settling", !!at_once || reduceMotion);
    var box = chosen.getBoundingClientRect();   // (to the fraction of a pixel, unlike offsetLeft)
    glider.style.width = box.width + "px";
    glider.style.transform = "translateX(" + (box.left - group.getBoundingClientRect().left - group.clientLeft) + "px)";
  }
  document.querySelectorAll(".unit-switch").forEach(function (group) {
    var glider = document.createElement("i");   // not a span: the switch styles its spans as choices
    glider.className = "unit-switch-glider";
    glider.setAttribute("aria-hidden", "true");
    group.insertBefore(glider, group.firstChild);
    group.classList.add("has-glider");
    group.addEventListener("change", function () { glide(group); });
    // placed where it belongs, without gliding, whenever the switch comes into view (a card opening)
    if (window.ResizeObserver) new ResizeObserver(function () { glide(group, true); }).observe(group);
    glide(group, true);
  });

  var lockForm = document.querySelector("[data-lock-form]");
  if (lockForm) {
    var lockOn = lockForm.querySelector("[data-lock-on]");
    var lockFields = lockForm.querySelector("[data-lock-fields]");
    var showLock = function () {
      lockFields.inert = !lockOn.checked;   // (not disabled: they're still sent, and kept)
      lockFields.classList.toggle("is-off", !lockOn.checked);
    };
    lockOn.addEventListener("change", showLock);
    showLock();
  }

  var form = document.querySelector("[data-checks-form]");
  if (!form) return;
  var on = form.querySelector("[data-checks-on]");
  var every = form.querySelector("[data-checks-every]");
  var custom = form.querySelector("[data-every-custom]");
  var row = form.querySelector("[data-custom-row]");
  var amount = form.querySelector("input[name=amount]");
  var hint = form.querySelector("[data-custom-hint]");
  var longest = hint.textContent;
  var PLACEHOLDERS = { minutes: "e.g. 30", hours: "e.g. 36", days: "e.g. 3" };

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
  function describe(minutes) {
    var parts = [[Math.floor(minutes / 1440), "day"], [Math.floor(minutes % 1440 / 60), "hour"], [minutes % 60, "minute"]]
      .filter(function (part) { return part[0]; })
      .map(function (part) { return plural(part[0], part[1]); });
    return parts.length > 1 ? parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] : parts.join("");
  }
  function unit() { return form.querySelector("input[name=unit]:checked").value; }
  function number() { return /^\d+$/.test(amount.value.trim()) ? Number(amount.value.trim()) : 0; }

  function show() {
    every.inert = !on.checked; // not disabled: a disabled choice wouldn't be sent
    every.classList.toggle("is-off", !on.checked);
    row.hidden = !custom.checked;
    var n = number();
    var minutes = n * PER[unit()];
    var word = unit().slice(0, -1);
    if (!n) hint.textContent = longest;
    else if (describe(minutes) === plural(n, word)) hint.textContent = "Every " + describe(minutes) + ".";   // 45 minutes
    else hint.textContent = plural(n, word) + " = " + describe(minutes) + ".";
    amount.placeholder = PLACEHOLDERS[unit()];
  }

  var was = unit();
  form.querySelectorAll("input[name=unit]").forEach(function (input) {
    input.addEventListener("change", function () {
      var minutes = number() * PER[was];
      if (minutes && minutes % PER[input.value] === 0 && minutes / PER[input.value] !== number()) {
        amount.value = minutes / PER[input.value];   // the same time, in the new unit
        amount.classList.remove("is-converted");
        void amount.offsetWidth;                     // play the fade again
        amount.classList.add("is-converted");
      }
      was = input.value;
      show();
    });
  });
  form.addEventListener("change", show);
  amount.addEventListener("input", show);
  custom.addEventListener("change", function () { if (custom.checked) amount.focus(); });
  show();
})();
