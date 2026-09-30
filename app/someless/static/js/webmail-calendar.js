// The calendar (webmail-calendar.html, calendar.py), as PrivateEmail's: a month, a week, the
// working week or a day, drawn from the events of the dates in view (in the reader's own time);
// hours 64 pixels tall, events side by side where they meet, a red line at the time now. An
// event opens in its own window (when, where, who, and an invitation's answer: Accept, Maybe,
// Decline) and is made or changed in its form: title, all day or its times, how it repeats (a
// custom rule too), its calendar, people invited, where, and a description. A repeating event is
// changed or deleted one time of it, or all of them, as asked. The month down the side picks a
// date; the calendars there are shown or hidden, renamed and coloured.
(function () {
  var root = document.querySelector("[data-wm-calendar]");
  if (!root || !window.wm) return;
  var viewBox = root.querySelector("[data-wm-cal-view]");
  var titleBox = root.querySelector("[data-wm-cal-title]");
  var eventsUrl = root.dataset.eventsUrl;
  var eventUrl = root.dataset.eventUrl;
  var calendarUrl = root.dataset.calendarUrl;
  var own = JSON.parse(root.dataset.own || "[]").map(function (one) { return one.toLowerCase(); });
  var calendars = JSON.parse(root.dataset.calendars || "[]");
  var HOUR = 64;
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var KEYS = ["su", "mo", "tu", "we", "th", "fr", "sa"];
  var ORDINALS = { 1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth" };
  var state = {
    view: root.dataset.view, date: parse(root.dataset.date), today: parse(root.dataset.today), events: [], range: null,
    mini: null, loaded: null,
  };
  var timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  var hourFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric" });

  // --- dates ---
  function pad(number) { return (number < 10 ? "0" : "") + number; }
  function parse(text) {
    var parts = String(text).split("-");
    return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  }
  function iso(day) { return day.getFullYear() + "-" + pad(day.getMonth() + 1) + "-" + pad(day.getDate()); }
  function isoTime(moment) { return pad(moment.getHours()) + ":" + pad(moment.getMinutes()); }
  function addDays(day, count) { return new Date(day.getFullYear(), day.getMonth(), day.getDate() + count, day.getHours(), day.getMinutes()); }
  function midnight(moment) { return new Date(moment.getFullYear(), moment.getMonth(), moment.getDate()); }
  function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
  function startOfWeek(day) { return addDays(midnight(day), -day.getDay()); }
  function local(text) {   // "2026-10-05T09:00"
    var date = text.slice(0, 10).split("-");
    var time = (text.slice(11, 16) || "00:00").split(":");
    return new Date(Number(date[0]), Number(date[1]) - 1, Number(date[2]), Number(time[0]), Number(time[1]));
  }
  function clock(moment) { return timeFormat.format(moment); }
  function longDate(day) { return DAYS[day.getDay()] + ", " + MONTHS[day.getMonth()] + " " + day.getDate(); }
  function shortDate(day) { return MONTHS[day.getMonth()].slice(0, 3) + " " + day.getDate() + ", " + day.getFullYear(); }

  function el(tag, className, text) {
    var made = document.createElement(tag);
    if (className) made.className = className;
    if (text !== undefined && text !== null) made.textContent = text;
    return made;
  }

  // --- what's in view ---
  function range() {
    var day = state.date;
    if (state.view === "month") {
      var first = new Date(day.getFullYear(), day.getMonth(), 1);
      var last = new Date(day.getFullYear(), day.getMonth() + 1, 0);
      return { start: startOfWeek(first), end: addDays(startOfWeek(last), 6) };
    }
    if (state.view === "week") {
      var sunday = startOfWeek(day);
      return { start: sunday, end: addDays(sunday, 6) };
    }
    if (state.view === "workweek") {
      var monday = addDays(startOfWeek(day), 1);
      return { start: monday, end: addDays(monday, 4) };
    }
    return { start: midnight(day), end: midnight(day) };
  }

  function title() {
    var shown = state.range;
    if (state.view === "month") return MONTHS[state.date.getMonth()] + " " + state.date.getFullYear();
    if (state.view === "day") return longDate(state.date) + ", " + state.date.getFullYear();
    var a = shown.start, b = shown.end;
    if (a.getFullYear() !== b.getFullYear()) return shortDate(a) + " – " + shortDate(b);
    if (a.getMonth() !== b.getMonth()) {
      return MONTHS[a.getMonth()].slice(0, 3) + " " + a.getDate() + " – " + MONTHS[b.getMonth()].slice(0, 3) + " " + b.getDate() + ", " + b.getFullYear();
    }
    return MONTHS[a.getMonth()] + " " + a.getDate() + " – " + b.getDate() + ", " + b.getFullYear();
  }

  function step(direction) {
    var day = state.date;
    if (state.view === "month") state.date = new Date(day.getFullYear(), day.getMonth() + direction, 1);
    else if (state.view === "day") state.date = addDays(day, direction);
    else state.date = addDays(day, 7 * direction);
    load();
  }

  // --- the events ---
  var loading = null;
  function load() {
    state.range = range();
    state.mini = new Date(state.date.getFullYear(), state.date.getMonth(), 1);
    var address = new URL(location.href);
    address.searchParams.set("view", state.view);
    address.searchParams.set("date", iso(state.date));
    history.replaceState(history.state, "", address.pathname + address.search);
    document.cookie = "wm_calendar_view=" + state.view + "; path=/; max-age=31536000; samesite=lax";
    root.querySelectorAll("[data-view]").forEach(function (button) {
      button.setAttribute("aria-checked", String(button.dataset.view === state.view));
    });
    titleBox.textContent = title();
    drawMini();
    var key = state.view + iso(state.range.start) + iso(state.range.end);
    if (state.loaded !== key) state.events = [];
    render();
    if (loading) loading.abort();
    loading = new AbortController();
    viewBox.setAttribute("aria-busy", "true");
    wm.loading(viewBox, true);
    return wm.request(eventsUrl + "?start=" + iso(state.range.start) + "&end=" + iso(state.range.end),
                      { signal: loading.signal, failTitle: "Couldn't load the events" }).then(function (answer) {
      loading = null;
      state.loaded = key;
      state.events = answer.events.map(function (one) {
        one.from = local(one.start);
        one.to = local(one.end);
        return one;
      });
      viewBox.setAttribute("aria-busy", "false");
      render(true);
      wm.loading(viewBox, false);
    }, function (error) {
      if (error && error.name === "AbortError") return;
      viewBox.setAttribute("aria-busy", "false");
      wm.loading(viewBox, false);
    });
  }
  function reload() {
    state.loaded = null;
    return load();
  }

  function eventsOn(day) {
    var begins = midnight(day), ends = addDays(begins, 1);
    return state.events.filter(function (one) {
      return (one.from < ends && one.to > begins) || (+one.from === +one.to && one.from >= begins && one.from < ends);
    });
  }
  function wholeDay(one) {
    return one.all_day || (one.to - one.from >= 24 * 3600 * 1000);
  }
  function classesOf(one) {
    var names = [];
    if (one.status === "declined") names.push("is-declined");
    else if (one.status === "needs-action") names.push("is-pending");
    else if (one.status === "tentative") names.push("is-tentative");
    if (one.cancelled) names.push("is-declined");
    return names.join(" ");
  }

  // --- drawing ---
  function render(withEvents) {
    var keep = viewBox.querySelector(".wm-grid-scroll");
    var scrolled = keep ? keep.scrollTop : null;
    var loader = viewBox.querySelector(":scope > .wm-loader");   // (still turning: kept)
    viewBox.innerHTML = "";
    if (loader) viewBox.appendChild(loader);
    viewBox.className = "wm-cal-view is-" + state.view + (withEvents ? " has-events" : "");
    if (state.view === "month") {
      drawMonth();
    } else {
      var days = [];
      for (var day = state.range.start; day <= state.range.end; day = addDays(day, 1)) days.push(day);
      drawGrid(days, scrolled);
    }
  }

  function chip(one, day) {
    var made = el("button", "wm-cal-chip " + classesOf(one));
    made.type = "button";
    made.style.setProperty("--event", one.color);
    made.dataset.event = one.id;
    var whole = wholeDay(one);
    if (whole) {
      made.classList.add("is-all-day");
    } else {
      made.appendChild(el("span", "wm-cal-dot"));
      if (!day || sameDay(one.from, day)) made.appendChild(el("span", "wm-cal-chip-time", clock(one.from)));
    }
    made.appendChild(el("span", "wm-cal-chip-title", one.title || "(no title)"));
    made.title = (one.title || "(no title)") + (whole ? "" : ", " + clock(one.from) + " – " + clock(one.to));
    made.addEventListener("click", function (event) {
      event.stopPropagation();
      openEvent(one);
    });
    return made;
  }

  function drawMonth() {
    var box = el("div", "wm-month");
    var head = el("div", "wm-month-head");
    DAYS.forEach(function (name) { head.appendChild(el("div", "wm-month-dayname", name.slice(0, 3))); });
    box.appendChild(head);
    var weeks = el("div", "wm-month-weeks");
    var count = 0;
    for (var week = state.range.start; week <= state.range.end; week = addDays(week, 7)) {
      count += 1;
      var row = el("div", "wm-month-week");
      for (var index = 0; index < 7; index += 1) {
        var day = addDays(week, index);
        var cell = el("div", "wm-month-day");
        cell.dataset.date = iso(day);
        if (day.getMonth() !== state.date.getMonth()) cell.classList.add("is-other");
        if (index === 0 || index === 6) cell.classList.add("is-weekend");
        if (sameDay(day, state.today)) cell.classList.add("is-today");
        var number = el("button", "wm-month-number", String(day.getDate()));
        number.type = "button";
        number.dataset.goDay = iso(day);
        number.setAttribute("aria-label", longDate(day));
        cell.appendChild(number);
        var list = el("div", "wm-month-events");
        eventsOn(day).forEach(function (one) { list.appendChild(chip(one, day)); });
        cell.appendChild(list);
        row.appendChild(cell);
      }
      weeks.appendChild(row);
    }
    weeks.style.setProperty("--weeks", count);
    box.appendChild(weeks);
    viewBox.appendChild(box);
    requestAnimationFrame(fitMonth);
  }

  // a day with more than fits: "+3 more", which opens the day
  function fitMonth() {
    viewBox.querySelectorAll(".wm-month-events").forEach(function (list) {
      var chips = Array.prototype.slice.call(list.children);
      if (list.scrollHeight <= list.clientHeight + 1) return;
      var room = list.clientHeight;
      var each = chips[0] ? chips[0].offsetHeight + 2 : 22;
      var fits = Math.max(0, Math.floor(room / each) - 1);
      chips.slice(fits).forEach(function (one) { one.hidden = true; });
      var more = el("button", "wm-cal-more", "+" + (chips.length - fits) + " more");
      more.type = "button";
      more.dataset.goDay = list.parentNode.dataset.date;
      list.appendChild(more);
    });
  }

  function drawGrid(days, scrolled) {
    var box = el("div", "wm-grid");
    box.style.setProperty("--days", days.length);
    var head = el("div", "wm-grid-head");
    head.appendChild(el("div", "wm-grid-corner"));
    days.forEach(function (day) {
      var cell = el("div", "wm-grid-dayhead");
      if (sameDay(day, state.today)) cell.classList.add("is-today");
      if (day.getDay() === 0 || day.getDay() === 6) cell.classList.add("is-weekend");
      cell.appendChild(el("span", "wm-grid-dayname", DAYS[day.getDay()].slice(0, 3)));
      var number = el("button", "wm-grid-daynum", String(day.getDate()));
      number.type = "button";
      number.dataset.goDay = iso(day);
      number.setAttribute("aria-label", longDate(day));
      cell.appendChild(number);
      head.appendChild(cell);
    });
    box.appendChild(head);

    var allDay = el("div", "wm-grid-allday");
    allDay.appendChild(el("div", "wm-grid-corner wm-grid-allday-label", "All day"));
    days.forEach(function (day) {
      var cell = el("div", "wm-grid-allday-cell");
      cell.dataset.date = iso(day);
      if (day.getDay() === 0 || day.getDay() === 6) cell.classList.add("is-weekend");
      eventsOn(day).filter(wholeDay).forEach(function (one) { cell.appendChild(chip(one, day)); });
      allDay.appendChild(cell);
    });
    box.appendChild(allDay);

    var scroll = el("div", "wm-grid-scroll");
    var body = el("div", "wm-grid-body");
    var hours = el("div", "wm-grid-hours");
    for (var hour = 0; hour < 24; hour += 1) {
      hours.appendChild(el("div", "wm-grid-hour", hour ? hourFormat.format(new Date(2026, 0, 1, hour)) : ""));
    }
    body.appendChild(hours);
    days.forEach(function (day) {
      var column = el("div", "wm-grid-column");
      column.dataset.date = iso(day);
      if (day.getDay() === 0 || day.getDay() === 6) column.classList.add("is-weekend");
      if (sameDay(day, state.today)) column.classList.add("is-today");
      var lane = el("div", "wm-grid-events");   // (10px kept free at the right, to click and make an event there)
      laidOut(eventsOn(day).filter(function (one) { return !wholeDay(one); }), day).forEach(function (placed) {
        lane.appendChild(block(placed, day));
      });
      column.appendChild(lane);
      body.appendChild(column);
    });
    scroll.appendChild(body);
    box.appendChild(scroll);
    viewBox.appendChild(box);
    drawNow();
    if (scrolled !== null && scrolled !== undefined) {
      scroll.scrollTop = scrolled;
    } else {
      var inView = days.some(function (day) { return sameDay(day, state.today); });
      var now = new Date();
      scroll.scrollTop = inView ? Math.max(0, (now.getHours() - 2) * HOUR) : 8 * HOUR - 8;
    }
  }

  // events that meet, side by side: each group of them shares the column's width
  function laidOut(list, day) {
    var begins = midnight(day), ends = addDays(begins, 1);
    var placed = list.map(function (one) {
      var from = one.from < begins ? begins : one.from;
      var to = one.to > ends ? ends : one.to;
      return { event: one, from: from, to: to < from ? from : to };
    }).sort(function (a, b) { return a.from - b.from || (b.to - b.from) - (a.to - a.from); });
    var group = [], groupEnd = 0, lanes = [];
    function close() {
      group.forEach(function (one) { one.lanes = lanes.length; });
      group = [];
      lanes = [];
    }
    placed.forEach(function (one) {
      var shownEnd = Math.max(+one.to, +one.from + 20 * 60 * 1000);
      if (group.length && +one.from >= groupEnd) close();
      var lane = lanes.findIndex(function (laneEnd) { return laneEnd <= +one.from; });
      if (lane < 0) {
        lane = lanes.length;
        lanes.push(shownEnd);
      } else {
        lanes[lane] = shownEnd;
      }
      one.lane = lane;
      group.push(one);
      groupEnd = group.length === 1 ? shownEnd : Math.max(groupEnd, shownEnd);
    });
    close();
    return placed;
  }

  function block(placed, day) {
    var one = placed.event;
    var minutes = (placed.from - midnight(day)) / 60000;
    var length = Math.max((placed.to - placed.from) / 60000, 20);
    var made = el("button", "wm-cal-block " + classesOf(one));
    made.type = "button";
    made.dataset.event = one.id;
    made.style.setProperty("--event", one.color);
    made.style.top = (minutes / 60 * HOUR) + "px";
    made.style.height = Math.max(length / 60 * HOUR - 2, 18) + "px";
    made.style.left = "calc(" + (placed.lane / placed.lanes * 100) + "% )";
    made.style.width = "calc(" + (100 / placed.lanes) + "% - 2px)";
    if (length < 45) made.classList.add("is-short");
    made.appendChild(el("span", "wm-cal-block-title", one.title || "(no title)"));
    made.appendChild(el("span", "wm-cal-block-time", clock(one.from) + " – " + clock(one.to)));
    if (one.location && length >= 75) made.appendChild(el("span", "wm-cal-block-where", one.location));
    made.addEventListener("click", function (event) {
      event.stopPropagation();
      openEvent(one);
    });
    return made;
  }

  // the red line at the time now (and its time beside the hours), moved each minute
  function drawNow() {
    viewBox.querySelectorAll(".wm-now, .wm-now-time").forEach(function (old) { old.remove(); });
    var now = new Date();
    var column = viewBox.querySelector('.wm-grid-column[data-date="' + iso(now) + '"]');
    if (!column) return;
    var top = (now.getHours() * 60 + now.getMinutes()) / 60 * HOUR;
    var line = el("div", "wm-now");
    line.style.top = top + "px";
    column.appendChild(line);
    var label = el("div", "wm-now-time", clock(now));
    label.style.top = top + "px";
    viewBox.querySelector(".wm-grid-hours").appendChild(label);
  }
  setInterval(function () {
    var now = new Date();
    if (!sameDay(now, state.today)) {
      state.today = midnight(now);
      render(true);
    }
    drawNow();
  }, 60000);

  // --- clicking the days: a date opens it, an empty time makes an event there ---
  viewBox.addEventListener("click", function (event) {
    var go = event.target.closest("[data-go-day]");
    if (go) {
      state.date = parse(go.dataset.goDay);
      state.view = "day";
      load();
      return;
    }
    var column = event.target.closest(".wm-grid-column");
    if (column && event.target === column) {
      var minutes = Math.floor(event.offsetY / (HOUR / 2)) * 30;
      openForm({ date: parse(column.dataset.date), minutes: Math.min(minutes, 23 * 60 + 30) });
      return;
    }
    var cell = event.target.closest(".wm-month-day, .wm-grid-allday-cell");
    if (cell && (event.target === cell || event.target.classList.contains("wm-month-events"))) {
      openForm({ date: parse(cell.dataset.date), allDay: cell.classList.contains("wm-grid-allday-cell") });
    }
  });

  root.querySelector("[data-wm-today]").addEventListener("click", function () {
    state.date = new Date(state.today);
    load();
  });
  root.querySelectorAll("[data-wm-step]").forEach(function (button) {
    button.addEventListener("click", function () { step(Number(button.dataset.wmStep)); });
  });
  root.querySelectorAll("[data-view]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.view = button.dataset.view;
      load();
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.target.closest("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft") step(-1);
    else if (event.key === "ArrowRight") step(1);
    else if (event.key === "t") root.querySelector("[data-wm-today]").click();
    else if (event.key === "c") openForm({});
    else return;
    event.preventDefault();
  });
  window.addEventListener("resize", function () {
    if (state.view === "month") render(true);
  });

  // --- the month down the side ---
  var mini = document.querySelector("[data-wm-mini]");
  function drawMini() {
    var month = state.mini;
    mini.querySelector("[data-wm-mini-title]").textContent = MONTHS[month.getMonth()] + " " + month.getFullYear();
    var grid = mini.querySelector("[data-wm-mini-grid]");
    grid.innerHTML = "";
    DAYS.forEach(function (name) { grid.appendChild(el("span", "wm-mini-dayname", name.slice(0, 1))); });
    var start = startOfWeek(month);
    for (var index = 0; index < 42; index += 1) {
      var day = addDays(start, index);
      var button = el("button", "wm-mini-day", String(day.getDate()));
      button.type = "button";
      button.dataset.day = iso(day);
      button.setAttribute("aria-label", longDate(day) + ", " + day.getFullYear());
      if (day.getMonth() !== month.getMonth()) button.classList.add("is-other");
      if (sameDay(day, state.today)) button.classList.add("is-today");
      if (sameDay(day, state.date)) button.classList.add("is-chosen");
      if (state.view !== "month" && state.view !== "day" && state.range && day >= state.range.start && day <= state.range.end) {
        button.classList.add("in-view");   // (the dates in view: one band, rounded at its ends)
        if (sameDay(day, state.range.start)) button.classList.add("is-band-start");
        if (sameDay(day, state.range.end)) button.classList.add("is-band-end");
      }
      grid.appendChild(button);
    }
  }
  mini.addEventListener("click", function (event) {
    var arrow = event.target.closest("[data-wm-mini-step]");
    if (arrow) {
      state.mini = new Date(state.mini.getFullYear(), state.mini.getMonth() + Number(arrow.dataset.wmMiniStep), 1);
      drawMini();
      return;
    }
    var day = event.target.closest("[data-day]");
    if (!day) return;
    state.date = parse(day.dataset.day);
    document.dispatchEvent(new CustomEvent("wm:side-close"));
    load();
  });

  // --- the calendars down the side ---
  var calendarList = document.querySelector("[data-wm-calendars]");
  function drawCalendars() {
    calendarList.innerHTML = "";
    calendars.forEach(function (calendar) {
      var item = el("li", "wm-calendar-item");
      item.style.setProperty("--cal", calendar.color);
      var toggle = el("label", "wm-calendar-toggle");
      var box = el("input");
      box.type = "checkbox";
      box.checked = calendar.visible;
      box.setAttribute("aria-label", "Show " + calendar.name);
      box.addEventListener("change", function () {
        wm.request(calendarUrl + "/" + encodeURIComponent(calendar.id), {
          method: "POST", body: { visible: box.checked }, failTitle: "Error occurred while saving calendar settings",
        }).then(function (answer) {
          calendars = answer.calendars;
          drawCalendars();
          reload();
        }, function () { box.checked = !box.checked; });
      });
      toggle.appendChild(box);
      toggle.appendChild(el("span", "wm-calendar-box"));
      toggle.appendChild(el("span", "wm-calendar-name", calendar.name));
      item.appendChild(toggle);
      var menu = el("button", "wm-icon wm-mini");
      menu.type = "button";
      menu.setAttribute("aria-label", "Calendar options");
      menu.setAttribute("data-tip", "Calendar options");
      menu.appendChild(wm.icon("more"));
      menu.addEventListener("click", function () {
        wm.menu(menu, [{ label: "Settings", icon: "settings", act: function () { calendarSettings(calendar); } }]);
      });
      item.appendChild(menu);
      calendarList.appendChild(item);
    });
  }

  var calendarDialog = document.querySelector("[data-wm-calendar-dialog]");
  var calendarForm = calendarDialog.querySelector("[data-wm-calendar-form]");
  var settingsFor = null;
  function calendarSettings(calendar) {
    settingsFor = calendar;
    calendarForm.querySelector('[name="name"]').value = calendar.name;
    calendarForm.querySelectorAll("[data-color]").forEach(function (swatch) {
      swatch.setAttribute("aria-checked", String(swatch.dataset.color.toLowerCase() === (calendar.color || "").toLowerCase()));
    });
    calendarForm.querySelector("[data-wm-problem]").hidden = true;
    calendarDialog.showModal();
  }
  calendarForm.querySelector("[data-wm-swatches]").addEventListener("click", function (event) {
    var swatch = event.target.closest("[data-color]");
    if (!swatch) return;
    calendarForm.querySelectorAll("[data-color]").forEach(function (other) {
      other.setAttribute("aria-checked", String(other === swatch));
    });
  });
  calendarDialog.addEventListener("click", function (event) {
    if (event.target === calendarDialog || event.target.closest("[data-wm-close]")) calendarDialog.close();
  });
  calendarForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var chosen = calendarForm.querySelector('[data-color][aria-checked="true"]');
    var problem = calendarForm.querySelector("[data-wm-problem]");
    wm.request(calendarUrl + "/" + encodeURIComponent(settingsFor.id), {
      method: "POST", quiet: true,
      body: { name: calendarForm.querySelector('[name="name"]').value, color: chosen ? chosen.dataset.color : settingsFor.color },
    }).then(function (answer) {
      calendars = answer.calendars;
      calendarDialog.close();
      wm.toast(answer.message || "Calendar settings saved");
      drawCalendars();
      fillCalendarSelect();
      reload();
    }, function (error) {
      problem.textContent = error.problem || "Error occurred while saving calendar settings";
      problem.hidden = false;
    });
  });

  // --- a choice of two (this event only, or all of them) ---
  function choose(options) {
    return new Promise(function (resolve) {
      var dialog = el("dialog", "wm-dialog");
      var card = el("div", "wm-dialog-card");
      card.appendChild(el("h2", "wm-dialog-title", options.title));
      if (options.text) card.appendChild(el("p", "wm-dialog-text", options.text));
      var actions = el("div", "wm-dialog-actions");
      var secondary = el("button", "wm-button is-ghost", options.secondary);
      secondary.type = "button";
      var primary = el("button", "wm-button" + (options.danger ? " is-danger" : ""), options.primary);
      primary.type = "button";
      actions.appendChild(secondary);
      actions.appendChild(primary);
      card.appendChild(actions);
      dialog.appendChild(card);
      document.body.appendChild(dialog);
      var answered = false;
      function done(value) {
        if (answered) return;
        answered = true;
        dialog.classList.add("is-leaving");
        setTimeout(function () {
          if (dialog.open) dialog.close();
          dialog.remove();
        }, wm.reduceMotion ? 0 : 160);
        resolve(value);
      }
      secondary.addEventListener("click", function () { done("this"); });
      primary.addEventListener("click", function () { done("all"); });
      dialog.addEventListener("cancel", function (event) {
        event.preventDefault();
        done(null);
      });
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) done(null);
      });
      dialog.showModal();
      primary.focus();
    });
  }

  // --- repeating: said in words ---
  function daysText(days) {
    var names = KEYS.filter(function (key) { return days.indexOf(key) >= 0; }).map(function (key) { return DAYS[KEYS.indexOf(key)]; });
    return names.join(", ");
  }
  function ruleText(rule, start) {
    if (!rule) return "";
    var every = rule.interval || 1;
    var text;
    if (rule.frequency === "daily") {
      text = every === 1 ? "Every day" : "Every " + every + " days";
    } else if (rule.frequency === "weekly") {
      var days = rule.days && rule.days.length ? rule.days : [KEYS[start.getDay()]];
      text = every === 1 ? "Every week on " + daysText(days) : "Every " + every + " weeks on " + daysText(days);
    } else if (rule.frequency === "monthly") {
      if (rule.ordinal) {
        var weekday = DAYS[start.getDay()];
        text = every === 1 ? "Monthly on the " + ORDINALS[rule.ordinal] + " " + weekday
                           : "Every " + every + " months on the " + ORDINALS[rule.ordinal] + " " + weekday;
      } else {
        var day = rule.month_day || start.getDate();
        text = every === 1 ? "Every month on day " + day : "Every " + every + " months on day " + day;
      }
    } else if (rule.frequency === "yearly") {
      text = every === 1 ? "Annually on " + MONTHS[start.getMonth()] + " " + start.getDate()
                         : "Every " + every + " years on " + MONTHS[start.getMonth()] + " " + start.getDate();
    } else {
      return "Custom recurrence";
    }
    if (rule.until) text += ", until " + shortDate(parse(rule.until));
    else if (rule.count) text += ", " + rule.count + " times";
    return text;
  }

  // --- an event's own window ---
  var viewDialog = document.querySelector("[data-wm-event-view]");
  var viewBody = viewDialog.querySelector("[data-wm-event-body]");
  var answerBar = viewDialog.querySelector("[data-wm-event-answer]");
  var viewing = null;

  function openEvent(one) {
    wm.request(eventUrl + "/" + encodeURIComponent(one.id), { failTitle: "Calendar event not found" }).then(function (answer) {
      showEvent(answer.event);
    }, function () { reload(); });
  }

  function whenText(one) {
    var from = local(one.start), to = local(one.end);
    if (one.all_day) {
      var last = addDays(to, -1);
      return sameDay(from, last) ? longDate(from) : longDate(from) + " – " + longDate(last);
    }
    if (sameDay(from, to)) return longDate(from) + " · " + clock(from) + " – " + clock(to);
    return longDate(from) + ", " + clock(from) + " – " + longDate(to) + ", " + clock(to);
  }

  function row(iconName, content, className) {
    var line = el("div", "wm-event-row" + (className ? " " + className : ""));
    line.appendChild(wm.icon(iconName));
    var holder = el("div", "wm-event-row-text");
    if (typeof content === "string") holder.textContent = content;
    else holder.appendChild(content);
    line.appendChild(holder);
    return line;
  }

  function showEvent(one) {
    viewing = one;
    viewBody.innerHTML = "";
    var heading = el("h2", "wm-event-title", one.title || "(no title)");
    heading.id = "event-view-title";
    heading.style.setProperty("--event", one.color);
    viewBody.appendChild(heading);
    viewBody.appendChild(row("clock", whenText(one), "is-when"));
    if (one.repeats && one.rule) viewBody.appendChild(row("refresh", el("span", "wm-event-tag", ruleText(one.rule, local(one.base_start || one.start)))));
    if (one.location) {
      var place = /^https?:\/\//i.test(one.location) ? el("a", "wm-event-link", one.location) : el("span", "", one.location);
      if (place.tagName === "A") {
        place.href = one.location;
        place.target = "_blank";
        place.rel = "noopener noreferrer";
      }
      viewBody.appendChild(row("pin", place, "is-where"));
    }
    var calendarLine = el("span", "wm-event-calendar", one.calendar_name || "Calendar");
    calendarLine.style.setProperty("--event", one.color);
    viewBody.appendChild(row("calendar", calendarLine));
    if (one.participants && one.participants.length) {
      var people = el("div", "wm-event-people");
      people.appendChild(el("p", "wm-event-people-title", "Participants · " + one.participants.length));
      one.participants.slice().sort(function (a, b) { return b.organizer - a.organizer; }).forEach(function (person) {
        var line = el("div", "wm-event-person is-" + person.status);
        var mark = el("span", "wm-event-status");
        mark.setAttribute("aria-label", { accepted: "Accepted", declined: "Declined", tentative: "Maybe", "needs-action": "Not answered" }[person.status] || "");
        line.appendChild(mark);
        var who = el("span", "wm-event-person-who");
        who.appendChild(el("span", "wm-event-person-name", person.name || person.email));
        if (person.name) who.appendChild(el("span", "wm-event-person-email", person.email));
        line.appendChild(who);
        if (person.organizer) line.appendChild(el("span", "wm-event-organizer", "Organizer"));
        people.appendChild(line);
      });
      viewBody.appendChild(row("user", people, "is-people"));
    }
    if (one.description) viewBody.appendChild(row("note", el("p", "wm-event-description", one.description)));
    viewDialog.querySelector("[data-wm-event-edit]").hidden = !one.is_organizer;
    answerBar.hidden = !one.status;
    drawAnswer(one.status);
    if (!viewDialog.open) viewDialog.showModal();
  }

  function drawAnswer(status) {
    answerBar.querySelectorAll("[data-answer]").forEach(function (button) {
      var on = button.dataset.answer === status;
      button.setAttribute("aria-checked", String(on));
      if (button.dataset.answer === "accepted") button.textContent = on ? "Accepted" : "Accept";
      if (button.dataset.answer === "declined") button.textContent = on ? "Declined" : "Decline";
    });
  }

  viewDialog.addEventListener("click", function (event) {
    if (event.target === viewDialog || event.target.closest("[data-wm-close]")) viewDialog.close();
  });
  answerBar.addEventListener("click", function (event) {
    var button = event.target.closest("[data-answer]");
    if (!button || !viewing) return;
    var status = button.dataset.answer;
    var asks = {
      accepted: { title: "Accept recurring event?", text: "This is a recurring event. Do you want to change your confirmation only for this event, or all events?",
                  secondary: "Accept this event only", primary: "Accept all events" },
      tentative: { title: "Mark recurring event as maybe?", text: "This is a recurring event. Do you want to mark as maybe only for this event, or all events?",
                   secondary: "Mark only this event as maybe", primary: "Mark all events as maybe" },
      declined: { title: "Decline recurring event?", text: "This is a recurring event. Do you want to decline only this event, or all events?",
                  secondary: "Decline this event only", primary: "Decline all events" },
    }[status];
    (viewing.repeats ? choose(asks) : Promise.resolve("this")).then(function (scope) {
      if (!scope) return;
      wm.request(eventUrl + "/" + encodeURIComponent(viewing.id) + "/reply", {
        method: "POST", body: { status: status, scope: scope }, failTitle: "Couldn't send your answer",
      }).then(function (answer) {
        viewing.status = status;
        drawAnswer(status);
        wm.toast(answer.message);
        reload();
      });
    });
  });

  viewDialog.querySelector("[data-wm-event-edit]").addEventListener("click", function () {
    if (!viewing) return;
    var one = viewing;
    (one.repeats ? choose({ title: "Edit recurring event", text: "This is a recurring event. Do you want to edit only this event, or all events?",
                            secondary: "Edit this event only", primary: "Edit all events" }) : Promise.resolve("all")).then(function (scope) {
      if (!scope) return;
      viewDialog.close();
      openForm({ event: one, scope: scope });
    });
  });

  viewDialog.querySelector("[data-wm-event-delete]").addEventListener("click", function () {
    if (!viewing) return;
    var one = viewing;
    var text = one.participants && one.participants.length > 1
      ? "Deleting this event will permanently remove it from the other participant’s agenda. Are you sure you would like to proceed?"
      : "This event will be permanently deleted. This action cannot be undone.";
    var asked = one.repeats
      ? choose({ title: "Delete event?", text: text, secondary: "Delete this event only", primary: "Delete all events", danger: true })
      : wm.confirm({ title: "Delete event?", text: text, yes: "Yes, delete event", no: "No, do not delete", danger: true }).then(function (yes) {
        return yes ? "this" : null;
      });
    asked.then(function (scope) {
      if (!scope) return;
      wm.request(eventUrl + "/" + encodeURIComponent(one.id) + "/delete", {
        method: "POST", body: { scope: scope }, failTitle: "Error occurred while deleting event",
      }).then(function (answer) {
        viewDialog.close();
        wm.toast(answer.message);
        reload();
      });
    });
  });

  // --- the form ---
  var formDialog = document.querySelector("[data-wm-event-form-dialog]");
  var form = formDialog.querySelector("[data-wm-event-form]");
  var problem = form.querySelector("[data-wm-problem]");
  var repeats = form.querySelector("[data-wm-repeats]");
  var repeatSet = form.querySelector("[data-wm-repeat-set]");
  var calendarSelect = form.querySelector("[data-wm-event-calendar]");
  var people = form.querySelector("[data-wm-people]");
  var peopleInput = form.querySelector("[data-wm-people-input]");
  var editing = null;
  var scope = "all";
  var customRule = null;
  var changed = false;
  var lastRepeat = "never";
  var ADDRESS = /^[^@\s<>(),;:"\[\]\\]+@[^@\s<>(),;:"\[\]\\]+\.[^@\s<>(),;:"\[\]\\]+$/;

  function field(name) { return form.querySelector('[name="' + name + '"]'); }

  function fillCalendarSelect() {
    var chosen = calendarSelect.value;
    calendarSelect.innerHTML = "";
    calendars.forEach(function (calendar) {
      var option = el("option", "", calendar.name);
      option.value = calendar.id;
      calendarSelect.appendChild(option);
    });
    if (chosen) calendarSelect.value = chosen;
  }

  function startDate() { return field("start_date").value ? parse(field("start_date").value) : state.date; }

  function setRule(rule) {
    customRule = rule;
    if (!rule) {
      repeats.value = "never";
    } else {
      var start = startDate();
      var simple = (rule.interval || 1) === 1 && !rule.until && !rule.count;
      if (simple && rule.frequency === "daily") repeats.value = "daily";
      else if (simple && rule.frequency === "weekly" && (!rule.days || !rule.days.length || (rule.days.length === 1 && rule.days[0] === KEYS[start.getDay()]))) repeats.value = "weekly";
      else if (simple && rule.frequency === "monthly" && !rule.ordinal && (!rule.month_day || rule.month_day === start.getDate())) repeats.value = "monthly";
      else if (simple && rule.frequency === "yearly") repeats.value = "yearly";
      else {
        repeatSet.hidden = false;
        repeatSet.textContent = ruleText(rule, start);
        repeats.value = "set";
      }
    }
    lastRepeat = repeats.value;
  }

  function currentRule() {
    var start = startDate();
    switch (repeats.value) {
      case "daily": return { frequency: "daily" };
      case "weekly": return { frequency: "weekly", days: [KEYS[start.getDay()]] };
      case "monthly": return { frequency: "monthly", month_day: start.getDate() };
      case "yearly": return { frequency: "yearly" };
      case "set": return customRule;
      default: return null;
    }
  }

  function chips() {
    return Array.prototype.map.call(people.querySelectorAll("[data-person]"), function (one) { return one.dataset.person; });
  }
  function addPerson(address) {
    address = address.trim().replace(/[,;]+$/, "");
    if (!address) return true;
    if (!ADDRESS.test(address)) {
      problem.textContent = "Invalid email address";
      problem.hidden = false;
      return false;
    }
    if (own.indexOf(address.toLowerCase()) >= 0 || chips().some(function (one) { return one.toLowerCase() === address.toLowerCase(); })) return true;
    var made = el("span", "wm-person-chip");
    made.dataset.person = address;
    made.appendChild(el("span", "", address));
    var remove = el("button", "wm-person-chip-x");
    remove.type = "button";
    remove.setAttribute("aria-label", "Remove participant");
    remove.appendChild(wm.icon("close"));
    remove.addEventListener("click", function () {
      made.remove();
      changed = true;
      peopleInput.focus();
    });
    made.appendChild(remove);
    people.insertBefore(made, peopleInput);
    changed = true;
    problem.hidden = true;
    return true;
  }
  peopleInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === "," || event.key === ";" || (event.key === "Tab" && peopleInput.value.trim())) {
      event.preventDefault();
      if (addPerson(peopleInput.value)) peopleInput.value = "";
    } else if (event.key === "Backspace" && !peopleInput.value) {
      var last = people.querySelector("[data-person]:last-of-type");
      if (last) {
        last.remove();
        changed = true;
      }
    }
  });
  peopleInput.addEventListener("blur", function () {
    if (peopleInput.value.trim() && addPerson(peopleInput.value)) peopleInput.value = "";
  });
  people.addEventListener("click", function (event) {
    if (event.target === people) peopleInput.focus();
  });
  // names and addresses from the contacts and mail, as they're typed
  var suggestTimer = null;
  peopleInput.addEventListener("input", function () {
    clearTimeout(suggestTimer);
    var typed = peopleInput.value.trim();
    if (!typed) return;
    suggestTimer = setTimeout(function () {
      wm.request(wm.root + "/compose/suggest?q=" + encodeURIComponent(typed), { quiet: true }).then(function (answer) {
        if (peopleInput.value.trim() !== typed || !answer.people.length) return;
        wm.menu(peopleInput, answer.people.slice(0, 6).map(function (person) {
          return { label: person.name ? person.name + " <" + person.email + ">" : person.email, icon: "user",
                   act: function () {
                     if (addPerson(person.email)) peopleInput.value = "";
                     peopleInput.focus();
                   } };
        }), { focus: false });
      }, function () {});
    }, 200);
  });

  function setTimes(from, to, allDay) {
    field("start_date").value = iso(from);
    field("start_time").value = isoTime(from);
    field("end_date").value = iso(allDay ? addDays(to, -1) : to);
    field("end_time").value = isoTime(to);
    field("all_day").checked = !!allDay;
    showTimes();
  }
  function showTimes() {
    var allDay = field("all_day").checked;
    form.querySelectorAll('[type="time"]').forEach(function (input) { input.hidden = allDay; });
  }

  function openForm(options) {
    options = options || {};
    editing = options.event || null;
    scope = options.scope || "all";
    form.querySelector("[data-wm-event-form-title]").textContent = editing ? "Edit event" : "Create event";
    form.querySelector("[data-wm-event-save]").textContent = editing ? "Save changes" : "Create event";
    fillCalendarSelect();
    people.querySelectorAll("[data-person]").forEach(function (one) { one.remove(); });
    peopleInput.value = "";
    repeatSet.hidden = true;
    problem.hidden = true;
    if (editing) {
      field("title").value = editing.title;
      setTimes(local(editing.start), local(editing.end), editing.all_day);
      field("location").value = editing.location || "";
      field("description").value = editing.description || "";
      calendarSelect.value = editing.calendar || (calendars[0] && calendars[0].id);
      (editing.participants || []).forEach(function (person) {
        if (own.indexOf(person.email.toLowerCase()) < 0) addPerson(person.email);
      });
      setRule(scope === "all" ? editing.rule : null);
    } else {
      field("title").value = "";
      var day = options.date || (sameDay(state.date, state.today) || state.view === "month" ? state.today : state.date);
      var from;
      if (options.minutes !== undefined) {
        from = new Date(day.getFullYear(), day.getMonth(), day.getDate(), Math.floor(options.minutes / 60), options.minutes % 60);
      } else {
        var now = new Date();
        from = sameDay(day, now) ? new Date(now.getFullYear(), now.getMonth(), now.getDate(), Math.min(now.getHours() + 1, 23))
                                 : new Date(day.getFullYear(), day.getMonth(), day.getDate(), 9);
      }
      var to = new Date(from.getTime() + 60 * 60000);
      setTimes(from, options.allDay ? addDays(midnight(from), 1) : to, !!options.allDay);
      field("location").value = "";
      field("description").value = "";
      var chosen = calendars.filter(function (one) { return one.default; })[0] || calendars[0];
      if (chosen) calendarSelect.value = chosen.id;
      setRule(null);
    }
    // one time of a repeating event can't repeat, nor move to another calendar, on its own
    repeats.disabled = !!(editing && editing.repeats && scope === "this");
    calendarSelect.disabled = repeats.disabled;
    changed = false;
    formDialog.showModal();
    field("title").focus();
  }
  document.querySelectorAll("[data-wm-create-event]").forEach(function (button) {
    button.addEventListener("click", function () { openForm({}); });
  });

  // the end keeps its distance from the start as the start moves
  var before = null;
  function remember() {
    before = { from: fromFields(), to: toFields() };
  }
  function fromFields() {
    var day = field("start_date").value ? parse(field("start_date").value) : null;
    if (!day) return null;
    var time = (field("start_time").value || "00:00").split(":");
    return new Date(day.getFullYear(), day.getMonth(), day.getDate(), Number(time[0]), Number(time[1]));
  }
  function toFields() {
    var day = field("end_date").value ? parse(field("end_date").value) : null;
    if (!day) return null;
    var time = (field("end_time").value || "00:00").split(":");
    return new Date(day.getFullYear(), day.getMonth(), day.getDate(), Number(time[0]), Number(time[1]));
  }
  ["start_date", "start_time"].forEach(function (name) {
    field(name).addEventListener("focus", remember);
    field(name).addEventListener("change", function () {
      var from = fromFields();
      if (!before || !before.from || !before.to || !from) return;
      var to = new Date(from.getTime() + (before.to - before.from));
      field("end_date").value = iso(to);
      field("end_time").value = isoTime(to);
      if (repeatSet.hidden === false && customRule) repeatSet.textContent = ruleText(customRule, startDate());
      remember();
    });
  });
  field("all_day").addEventListener("change", showTimes);
  form.addEventListener("input", function () { changed = true; });
  form.addEventListener("change", function () { changed = true; });

  // --- Custom recurrence ---
  var repeatDialog = document.querySelector("[data-wm-repeat-dialog]");
  var repeatForm = repeatDialog.querySelector("[data-wm-repeat-form]");
  function repeatField(name) { return repeatForm.querySelector('[name="' + name + '"]'); }
  function showRepeatParts() {
    var frequency = repeatField("frequency").value;
    repeatForm.querySelector("[data-wm-repeat-days]").hidden = frequency !== "weekly";
    repeatForm.querySelector("[data-wm-repeat-monthly]").hidden = frequency !== "monthly";
  }
  function openRepeat() {
    var start = startDate();
    var rule = customRule || { frequency: "weekly", interval: 1, days: [KEYS[start.getDay()]] };
    repeatField("frequency").value = rule.frequency;
    repeatField("interval").value = rule.interval || 1;
    repeatForm.querySelectorAll("[data-day]").forEach(function (button) {
      var days = rule.days && rule.days.length ? rule.days : [KEYS[start.getDay()]];
      button.setAttribute("aria-pressed", String(days.indexOf(button.dataset.day) >= 0));
    });
    repeatForm.querySelector("[data-wm-repeat-on-day]").textContent = "On day " + start.getDate();
    repeatForm.querySelector("[data-wm-repeat-on-ordinal]").textContent =
      "On the " + ORDINALS[Math.ceil(start.getDate() / 7)] + " " + DAYS[start.getDay()];
    repeatForm.querySelector('[name="monthly"][value="' + (rule.ordinal ? "ordinal" : "day") + '"]').checked = true;
    repeatForm.querySelector('[name="ends"][value="' + (rule.until ? "on" : rule.count ? "after" : "never") + '"]').checked = true;
    repeatField("until").value = rule.until || iso(addDays(start, 30));
    repeatField("count").value = rule.count || 10;
    repeatForm.querySelector("[data-wm-problem]").hidden = true;
    showRepeatParts();
    repeatDialog.showModal();
  }
  repeatField("frequency").addEventListener("change", showRepeatParts);
  repeatForm.querySelector("[data-wm-repeat-days]").addEventListener("click", function (event) {
    var button = event.target.closest("[data-day]");
    if (!button) return;
    button.setAttribute("aria-pressed", String(button.getAttribute("aria-pressed") !== "true"));
  });
  repeats.addEventListener("focus", function () { lastRepeat = repeats.value; });
  repeats.addEventListener("change", function () {
    if (repeats.value === "custom") {
      openRepeat();
      return;
    }
    if (repeats.value !== "set") repeatSet.hidden = true;
    lastRepeat = repeats.value;
  });
  function closeRepeat() {
    repeatDialog.close();
    if (repeats.value === "custom") repeats.value = lastRepeat;
  }
  repeatForm.querySelector("[data-wm-repeat-cancel]").addEventListener("click", closeRepeat);
  repeatDialog.addEventListener("cancel", function (event) {
    event.preventDefault();
    closeRepeat();
  });
  repeatForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var start = startDate();
    var problemLine = repeatForm.querySelector("[data-wm-problem]");
    var interval = Math.max(1, Math.min(999, Number(repeatField("interval").value) || 1));
    var rule = { frequency: repeatField("frequency").value, interval: interval };
    if (rule.frequency === "weekly") {
      rule.days = Array.prototype.map.call(repeatForm.querySelectorAll('[data-day][aria-pressed="true"]'), function (button) {
        return button.dataset.day;
      });
      if (!rule.days.length) rule.days = [KEYS[start.getDay()]];
    }
    if (rule.frequency === "monthly") {
      if (repeatForm.querySelector('[name="monthly"]:checked').value === "ordinal") rule.ordinal = Math.ceil(start.getDate() / 7);
      else rule.month_day = start.getDate();
    }
    var ends = repeatForm.querySelector('[name="ends"]:checked').value;
    if (ends === "on") {
      if (!repeatField("until").value || parse(repeatField("until").value) < midnight(start)) {
        problemLine.textContent = "End date must be on or after event start date";
        problemLine.hidden = false;
        return;
      }
      rule.until = repeatField("until").value;
    } else if (ends === "after") {
      rule.count = Math.max(1, Math.min(999, Number(repeatField("count").value) || 1));
    }
    customRule = rule;
    repeatSet.hidden = false;
    repeatSet.textContent = ruleText(rule, start);
    repeats.value = "set";
    lastRepeat = "set";
    changed = true;
    repeatDialog.close();
  });

  // --- the form: closed, or sent ---
  function cancelForm() {
    if (!changed) {
      formDialog.close();
      return;
    }
    wm.confirm({ title: "Discard event?", text: "This event will not be saved.", yes: "Yes, discard", no: "No, do not discard",
                 danger: true }).then(function (yes) {
      if (yes) formDialog.close();
    });
  }
  form.querySelectorAll("[data-wm-event-cancel]").forEach(function (button) { button.addEventListener("click", cancelForm); });
  formDialog.addEventListener("cancel", function (event) {
    event.preventDefault();
    cancelForm();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    problem.hidden = true;
    if (peopleInput.value.trim()) {
      if (!addPerson(peopleInput.value)) return;
      peopleInput.value = "";
    }
    var body = {
      title: field("title").value, all_day: field("all_day").checked,
      start_date: field("start_date").value, start_time: field("start_time").value,
      end_date: field("end_date").value, end_time: field("end_time").value,
      repeat: repeats.disabled ? null : currentRule(), calendar: calendarSelect.value, participants: chips(),
      location: field("location").value, description: field("description").value, scope: scope,
    };
    if (!body.title.trim()) {
      problem.textContent = "A valid event title is required";
      problem.hidden = false;
      field("title").focus();
      return;
    }
    var save = form.querySelector("[data-wm-event-save]");
    save.disabled = true;
    wm.request(editing ? eventUrl + "/" + encodeURIComponent(editing.id) : eventUrl, { method: "POST", body: body, quiet: true })
      .then(function (answer) {
        save.disabled = false;
        changed = false;
        formDialog.close();
        wm.toast(answer.message);
        var shownDay = parse(body.start_date);
        if (shownDay < state.range.start || shownDay > state.range.end) state.date = shownDay;
        reload();
      }, function (error) {
        save.disabled = false;
        problem.textContent = error.problem || (editing ? "Error occurred while updating event" : "Error occurred while creating event");
        problem.hidden = false;
      });
  });

  drawCalendars();
  fillCalendarSelect();
  load();
})();
