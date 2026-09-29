// The webmail's search field (webmail-mail.html), as PrivateEmail's: as you type, the first
// messages that say it show in a panel below (mail.py /search, the words in bold), in the folder
// being looked at (its chip; its x searches all the mail) or in all of it. The arrows move
// through them, Enter opens the one picked or lists all of them ("All results"), Escape closes.
// Empty, the field shows the recent searches (kept in this browser), each with an x to forget it.
(function () {
  var form = document.querySelector("[data-wm-search]");
  if (!form || !window.wm) return;
  var input = form.querySelector("#wm-search");
  var scope = form.querySelector("[data-wm-search-scope]");
  var panel = form.querySelector("[data-wm-search-panel]");
  var body = form.querySelector("[data-wm-search-body]");
  var recent = form.querySelector("[data-wm-recent]");
  var recentList = form.querySelector("[data-wm-recent-list]");
  var chipAll = form.querySelector("[data-wm-chip-all]");
  var chipFolder = form.querySelector("[data-wm-chip-folder]");
  var chipName = form.querySelector("[data-wm-chip-name]");
  var KEEP = 6;          // recent searches kept
  var WAIT = 250;        // ms after the last key before asking
  var STORE = "wm_recent_searches";
  var timer = null;
  var asking = null;
  var active = -1;

  // the folder searched: the one being looked at, until its chip's x says all the mail
  var folderKey, folderName;
  function lookAt() {
    folderKey = form.dataset.folder || scope.value;
    folderName = form.dataset.folderName || folderNameOf(scope.value);
    if (!scope.value && form.dataset.folder) scope.value = form.dataset.folder;
  }
  lookAt();
  document.addEventListener("wm:navigated", function () {
    lookAt();
    body.innerHTML = "";
    close();
  });

  function folderNameOf(key) {
    var row = key && document.querySelector('[data-wm-folders] .wm-folder[data-folder="' + CSS.escape(key) + '"]');
    return row ? row.dataset.name : "";
  }

  function showChips() {
    var inFolder = !!scope.value;
    chipAll.classList.toggle("is-on", !inFolder);
    chipFolder.hidden = !folderKey;
    chipFolder.classList.toggle("is-on", inFolder);
    chipName.textContent = folderName;
  }

  // --- recent searches, in this browser ---
  function remembered() {
    try {
      var kept = JSON.parse(localStorage.getItem(STORE) || "[]");
      return Array.isArray(kept) ? kept.filter(function (text) { return typeof text === "string"; }) : [];
    } catch (error) {
      return [];
    }
  }
  function remember(text) {
    text = text.trim();
    if (!text) return;
    var kept = remembered().filter(function (other) { return other.toLowerCase() !== text.toLowerCase(); });
    kept.unshift(text);
    try {
      localStorage.setItem(STORE, JSON.stringify(kept.slice(0, KEEP)));
    } catch (error) { /* (a private window: not kept) */ }
  }
  function forget(text) {
    try {
      localStorage.setItem(STORE, JSON.stringify(remembered().filter(function (other) { return other !== text; })));
    } catch (error) { /* (a private window) */ }
  }

  function drawRecent() {
    var kept = remembered();
    recentList.innerHTML = "";
    kept.forEach(function (text) {
      var item = document.createElement("li");
      item.className = "wm-search-recent-item";
      var go = document.createElement("button");
      go.type = "button";
      go.className = "wm-search-recent-go";
      go.appendChild(wm.icon("clock"));
      var words = document.createElement("span");
      words.textContent = text;
      go.appendChild(words);
      go.addEventListener("click", function () {
        input.value = text;
        submit();
      });
      var drop = document.createElement("button");
      drop.type = "button";
      drop.className = "wm-search-recent-x";
      drop.setAttribute("aria-label", "Remove from recent searches");
      drop.title = "Remove from recent searches";
      drop.appendChild(wm.icon("close"));
      drop.addEventListener("click", function (event) {
        event.stopPropagation();
        forget(text);
        drawRecent();
        input.focus();
      });
      item.appendChild(go);
      item.appendChild(drop);
      recentList.appendChild(item);
    });
    recent.hidden = !kept.length;
    return kept.length;
  }

  // --- the panel ---
  function open() {
    showChips();
    panel.hidden = false;
    input.setAttribute("aria-expanded", "true");
    form.classList.add("is-open");
  }
  function close() {
    panel.hidden = true;
    input.setAttribute("aria-expanded", "false");
    form.classList.remove("is-open");
    active = -1;
  }

  function skeleton() {
    var rows = "";
    for (var index = 0; index < 5; index++) {
      rows += '<div class="wm-search-skeleton"><span></span><span></span><span></span><span></span></div>';
    }
    body.innerHTML = rows;
  }

  function ask() {
    var text = input.value.trim();
    if (asking) asking.abort();
    if (!text) {
      body.innerHTML = "";
      drawRecent();
      return;
    }
    recent.hidden = true;
    skeleton();
    var controller = asking = new AbortController();
    var url = form.action + "?q=" + encodeURIComponent(text) + (scope.value ? "&in=" + encodeURIComponent(scope.value) : "");
    wm.request(url, { signal: controller.signal, quiet: true }).then(function (answer) {
      if (asking !== controller) return;
      asking = null;
      body.innerHTML = answer.html;
      active = -1;
    }, function (error) {
      if (error.name === "AbortError") return;
      asking = null;
      body.innerHTML = '<p class="wm-search-failed">Error occured while loading emails</p>';
    });
  }

  function submit() {
    var text = input.value.trim();
    if (!text) return;
    remember(text);
    close();
    input.blur();
    var url = form.action + "?q=" + encodeURIComponent(text) + (scope.value ? "&in=" + encodeURIComponent(scope.value) : "");
    if (wm.go) wm.go(url);
    else location.href = url;
  }

  function results() {
    return Array.prototype.slice.call(body.querySelectorAll("[data-wm-result], [data-wm-all-results]"));
  }
  function pick(index) {
    var all = results();
    all.forEach(function (item) {
      item.classList.remove("is-active");
      var option = item.closest("[role=option]");
      if (option) option.setAttribute("aria-selected", "false");
    });
    active = index;
    if (all[index]) {
      all[index].classList.add("is-active");
      var option = all[index].closest("[role=option]");
      if (option) option.setAttribute("aria-selected", "true");
      all[index].scrollIntoView({ block: "nearest" });
    }
  }

  input.addEventListener("focus", function () {
    open();
    if (!input.value.trim()) drawRecent();
    else if (!body.innerHTML) ask();
  });
  input.addEventListener("input", function () {
    open();
    clearTimeout(timer);
    timer = setTimeout(ask, WAIT);
  });
  input.addEventListener("keydown", function (event) {
    var all = results();
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!all.length) return;
      event.preventDefault();
      var next = active + (event.key === "ArrowDown" ? 1 : -1);   // (-1: back in the field)
      if (next < -1) next = all.length - 1;
      if (next >= all.length) next = -1;
      pick(next);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0 && all[active]) {
        remember(input.value);
        close();
        if (wm.go) wm.go(all[active].href);
        else location.href = all[active].href;
      } else {
        submit();
      }
    } else if (event.key === "Escape") {
      if (!panel.hidden) {
        event.preventDefault();
        close();
      } else if (input.value) {
        input.value = "";
      }
    }
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    submit();
  });
  body.addEventListener("click", function (event) {
    var link = event.target.closest("[data-wm-result], [data-wm-all-results]");
    if (link) remember(input.value);
  });

  chipAll.addEventListener("click", function () {
    scope.value = "";
    showChips();
    ask();
    input.focus();
  });
  chipFolder.addEventListener("click", function (event) {
    if (event.target.closest("[data-wm-chip-remove]")) {
      scope.value = "";
    } else {
      scope.value = folderKey;
    }
    showChips();
    ask();
    input.focus();
  });

  document.addEventListener("mousedown", function (event) {
    if (!panel.hidden && !form.contains(event.target)) close();
  });
  // "/" puts the cursor in the search field, as in most webmails
  document.addEventListener("keydown", function (event) {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
    var target = event.target;
    if (target.closest && target.closest("input, textarea, select, [contenteditable], dialog")) return;
    event.preventDefault();
    input.focus();
  });
  showChips();
})();
