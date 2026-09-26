// Dates in the admin's own time: the server knows only its own clock and time zone, so it
// writes each moment as it is (<time datetime data-local-date>), and this shows it in the
// browser's time zone, like "Sep 26, 2027" (<time data-local-moment>: "Sep 26, 2027, 3:04 PM"). A choice of how long something lasts
// (<option data-label data-days|data-months>) is counted from the admin's own clock too:
// "1 year (Sep 26, 2027)". Runs before dropdown.js, which shows the options as written here.
(function () {
  var format = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
  var formatMoment = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });

  // now, moved on by days, or by calendar months (Jan 31 + 1 month: Feb 28)
  function after(days, months) {
    var date = new Date();
    if (months) {
      var day = date.getDate();
      date.setDate(1);
      date.setMonth(date.getMonth() + months);
      var last = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
      date.setDate(Math.min(day, last));
    } else {
      date.setDate(date.getDate() + days);
    }
    return date;
  }

  function localize(root) {
    root.querySelectorAll("time[data-local-date]").forEach(function (time) {
      var moment = new Date(time.getAttribute("datetime"));
      if (!isNaN(moment)) time.textContent = format.format(moment);
    });
    root.querySelectorAll("time[data-local-moment]").forEach(function (time) {
      var moment = new Date(time.getAttribute("datetime"));
      if (!isNaN(moment)) time.textContent = formatMoment.format(moment);
    });
    root.querySelectorAll("option[data-days], option[data-months]").forEach(function (option) {
      var until = after(Number(option.dataset.days || 0), Number(option.dataset.months || 0));
      option.textContent = option.dataset.label + " (" + format.format(until) + ")";
    });
  }

  localize(document);
  window.somelessLocalTime = localize; // for a part of the page a script brings in (senders-page.js)
  document.addEventListener("someless:swap", function (event) { localize(event.detail.main); });
})();
