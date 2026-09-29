// The webmail's shared pieces (webmail-mail.html), for its other scripts, as window.wm:
//   wm.request(url, {method, body, quiet}) : the webmail's answer, as JSON (a promise). Logged out
//     meanwhile: to the login page. Refused: the notice board says why (unless quiet), and the
//     promise fails with the problem.
//   wm.toast(message, {warning}) : a toast, as PrivateEmail says what was done; errors go on the board
//   wm.board(title, message) : an error on the notice board (board.js)
//   wm.icon(name) : one of the page's icons (#wm-icons)
//   wm.copy(text) : onto the clipboard (a promise); a button with data-wm-copy does it by itself
//   wm.loading(holder, on, {page, label}) : the loading animation over holder (a positioned
//     element), or gone; a link with data-wm-page-link puts it over [data-wm-main] as the next
//     page comes. wm.spinner() : a small one to put in a line (wm.spinner.stop(it) when done)
//   wm.menu(at, items, {onClose}) : a menu at an element or a point ({x, y}): the three dots, a
//     right-click. items: {label, icon, act, trailing, switchOn, hidden, submenu} or "-" between.
//   wm.confirm({title, text, yes, no, danger}) : a dialog asking first (a promise of true or false)
//   wm.pickFolder(at, {title, current, create}) : the folder picker ("Move to folder"): the key
//     of the folder chosen, or null
//   wm.counts(counts, unread) : the folders' counts, and the Inbox's unread in the tab's title
//   wm.folders() : the folders as the side column lists them
(function () {
  var csrf = document.querySelector('meta[name="csrf-token"]');
  var toasts = document.querySelector("[data-wm-toasts]");
  var icons = document.getElementById("wm-icons");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var TOAST_MS = 4000;

  function board(title, message) {
    if (window.somelessBoard) window.somelessBoard.show({ type: "error", title: title, message: message || "" });
  }

  function request(url, options) {
    options = options || {};
    var init = { method: options.method || "GET", credentials: "same-origin", headers: { Accept: "application/json" } };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    if (init.method !== "GET" && csrf) init.headers["X-CSRFToken"] = csrf.content;
    if (options.signal) init.signal = options.signal;
    var spinning = spinnerFor(init.method);   // (the button clicked for it, turning till it's done)
    return fetch(url, init).then(function (response) {
      if (response.redirected && /\/login\b/.test(response.url)) {
        location.href = response.url;
        return new Promise(function () {});   // (the page goes)
      }
      return response.json().catch(function () { return {}; }).then(function (answer) {
        if (response.status === 401 && answer.login) {
          location.href = answer.login;
          return new Promise(function () {});
        }
        if (!response.ok) {
          var problem = answer.problem || "Something went wrong. Try to reload the page.";
          if (!options.quiet) board(options.failTitle || "That didn't work", problem);
          var error = new Error(problem);
          error.problem = problem;
          error.status = response.status;
          error.answer = answer;
          throw error;
        }
        return answer;
      });
    }, function (error) {
      if (error.name === "AbortError") throw error;
      if (!options.quiet) board(options.failTitle || "The webmail didn't answer", "Check your connection and try again.");
      throw error;
    }).then(function (answer) {
      stopSpinner(spinning);
      return answer;
    }, function (error) {
      stopSpinner(spinning);
      throw error;
    });
  }

  function icon(name) {
    var found = icons && icons.content.querySelector('[data-icon="' + name + '"] svg');
    return found ? found.cloneNode(true) : document.createElement("span");
  }

  // --- toasts: at the bottom of the page, one after another, gone after a few seconds ---
  function toast(message, options) {
    if (!toasts || !message) return;
    options = options || {};
    var item = document.createElement("div");
    item.className = "wm-toast" + (options.warning ? " is-warning" : "");
    item.appendChild(icon(options.warning ? "warning" : "check"));
    var text = document.createElement("span");
    text.textContent = message;
    item.appendChild(text);
    var close = document.createElement("button");
    close.type = "button";
    close.className = "wm-toast-close";
    close.setAttribute("aria-label", "Close");
    close.appendChild(icon("close"));
    item.appendChild(close);
    toasts.appendChild(item);
    while (toasts.children.length > 3) toasts.firstElementChild.remove();
    var timer;
    function go() {
      clearTimeout(timer);
      if (!item.isConnected) return;
      item.classList.add("is-leaving");
      setTimeout(function () { item.remove(); }, reduceMotion ? 0 : 220);
    }
    function wait() { timer = setTimeout(go, TOAST_MS); }
    close.addEventListener("click", go);
    item.addEventListener("mouseenter", function () { clearTimeout(timer); });
    item.addEventListener("mouseleave", wait);
    wait();
  }

  // --- copying: the clipboard, or on a plain http:// address (where browsers keep it shut) the
  // older way, through a hidden text box (in the open dialog, if any: the page behind can't be
  // selected) ---
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var box = document.createElement("textarea");
      box.value = text;
      box.setAttribute("readonly", "");
      box.style.cssText = "position: fixed; top: 0; left: 0; opacity: 0; pointer-events: none;";
      (document.querySelector("dialog[open]") || document.body).appendChild(box);
      box.select();
      var copied = false;
      try {
        copied = document.execCommand("copy");
      } catch (error) {
        // not allowed: said below
      }
      box.remove();
      if (copied) resolve();
      else reject(new Error("copy refused"));
    });
  }

  // a button with data-wm-copy copies it, and a toast says so (data-copied: what it says)
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-wm-copy]");
    if (!button) return;
    copy(button.dataset.wmCopy).then(function () {
      toast(button.dataset.copied || "Copied");
    }, function () {
      board("Couldn't copy", "Select the text and copy it yourself.");
    });
  });

  // --- loading: the turning arrows (lottie/webmail-loading.json) over the part of the page that's
  // coming, as PrivateEmail shows its dots: the folder's mail, a message, the next page ---
  var loaderSource = document.querySelector('meta[name="wm-loader"]');
  var loaderData = null;
  var loaderAsked = null;
  function loaderAnimation() {
    if (!loaderAsked && loaderSource && window.fetch) {
      loaderAsked = fetch(loaderSource.content).then(function (response) { return response.json(); })
        .then(function (data) { loaderData = data; return data; }, function () { return null; });
    }
    return loaderAsked || Promise.resolve(null);
  }
  function loading(holder, on, options) {
    if (!holder) return;
    options = options || {};
    var box = holder.querySelector(":scope > .wm-loader");
    if (!on) {
      if (!box || box.classList.contains("is-leaving")) return;
      box.classList.add("is-leaving");
      setTimeout(function () {
        if (box.player) box.player.destroy();
        box.remove();
      }, reduceMotion ? 0 : 160);
      return;
    }
    if (box) {
      box.classList.remove("is-leaving");
      return;
    }
    box = document.createElement("div");
    box.className = "wm-loader" + (options.page ? " is-page" : "");
    box.setAttribute("role", "status");
    box.setAttribute("aria-label", "Loading");
    if (options.page) {   // over what's in sight of it, however far it's scrolled
      var rect = holder.getBoundingClientRect();
      box.style.position = "fixed";
      box.style.inset = "auto";
      box.style.left = rect.left + "px";
      box.style.top = rect.top + "px";
      box.style.width = rect.width + "px";
      box.style.height = rect.height + "px";
    }
    var art = document.createElement("span");
    art.className = "wm-loader-art";
    art.setAttribute("aria-hidden", "true");
    box.appendChild(art);
    if (options.label) {   // what's happening, under the arrows ("Adding the picture…")
      var caption = document.createElement("span");
      caption.className = "wm-loader-label";
      caption.textContent = options.label;
      box.appendChild(caption);
      box.setAttribute("aria-label", options.label);
    }
    holder.appendChild(box);
    play(art, function (player) { box.player = player; });
  }
  function play(art, done) {
    loaderAnimation().then(function (data) {
      if (!data || !window.lottie) {
        art.classList.add("is-plain");   // (a turning ring instead)
        return;
      }
      if (!art.isConnected || art.dataset.playing) return;
      art.dataset.playing = "1";
      done(window.lottie.loadAnimation({ container: art, renderer: "svg", loop: true, autoplay: !reduceMotion,
                                         animationData: JSON.parse(JSON.stringify(data)) }));
    });
  }
  // a small one, in a line (a file on its way): wm.spinner() to put in, wm.spinner.stop(it) when done
  function spinner() {
    var art = document.createElement("span");
    art.className = "wm-loader-art is-small";
    art.setAttribute("aria-hidden", "true");
    setTimeout(function () { play(art, function (player) { art.player = player; }); }, 0);   // (once it's in the page)
    return art;
  }
  spinner.stop = function (art) {
    if (!art) return;
    if (art.player) art.player.destroy();
    art.remove();
  };
  // a page left for the next (Settings' parts, Contacts, the calendar): the loader at once
  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest("a[href][data-wm-page-link]");
    if (!link || link.target || link.hasAttribute("download") || link.getAttribute("aria-current") === "page") return;
    var url = new URL(link.href, location.href);
    if (url.origin !== location.origin || (url.pathname === location.pathname && url.search === location.search)) return;
    var group = link.closest("[data-wm-page-links]");
    if (group) {   // the part chosen shows so at once
      group.querySelectorAll(".is-current").forEach(function (one) { one.classList.remove("is-current"); });
      link.classList.add("is-current");
    }
    loading(document.querySelector("[data-wm-main]"), true, { page: true });
  });
  window.addEventListener("pageshow", function (event) {   // (back to this page: nothing's loading)
    if (event.persisted) document.querySelectorAll(".wm-loader").forEach(function (box) { box.remove(); });
  });

  // --- buttons: a burst of light as each is clicked (sparks from the big ones); one whose click
  // sends something turns into a spinner until the answer comes (request, below) ---
  var FLARED = "button, a.wm-button, a.wm-icon, a.wm-app, a.wm-settings-back";
  var CALM = ".wm-menu-item, .wm-cal-chip, .wm-cal-block, .wm-cal-more, .wm-mini-day, .wm-month-number, .wm-grid-daynum, " +
             ".wm-repeat-day, .wm-swatch, [data-format], .wm-toast-close, .wm-search-chip-x, .wm-person-chip-x, [data-no-flare]";
  var BIG = ".wm-button:not(.is-ghost), .wm-compose, .wm-cal-fab, .wm-settings-back";
  var pressed = null;   // the button just clicked, and when
  function flare(button) {
    var rect = button.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var made = document.createElement("span");
    made.className = "wm-flare";
    made.setAttribute("aria-hidden", "true");
    made.style.left = rect.left + "px";
    made.style.top = rect.top + "px";
    made.style.width = rect.width + "px";
    made.style.height = rect.height + "px";
    made.style.setProperty("--flare-radius", getComputedStyle(button).borderRadius || "999px");
    if (button.matches(".is-danger, .is-danger-text")) made.style.setProperty("--flare", "242, 92, 92");
    if (button.matches(BIG)) {
      for (var index = 0; index < 12; index += 1) {   // from its edge, outwards (its words stay clear)
        var spark = document.createElement("i");
        var angle = Math.PI * 2 * index / 12 + Math.random() * 0.35;
        var halfWidth = rect.width / 2, halfHeight = rect.height / 2;
        spark.style.setProperty("--sx", Math.round(Math.cos(angle) * halfWidth * 0.92) + "px");
        spark.style.setProperty("--sy", Math.round(Math.sin(angle) * halfHeight * 0.92) + "px");
        spark.style.setProperty("--x", Math.round(Math.cos(angle) * (halfWidth + 16 + Math.random() * 22)) + "px");
        spark.style.setProperty("--y", Math.round(Math.sin(angle) * (halfHeight + 14 + Math.random() * 18)) + "px");
        spark.style.animationDelay = Math.round(Math.random() * 50) + "ms";
        made.appendChild(spark);
      }
    }
    (button.closest("dialog[open]") || document.body).appendChild(made);   // (a dialog is on top of the page)
    setTimeout(function () { made.remove(); }, 900);
    button.classList.remove("is-flaring");
    void button.offsetWidth;   // (again, for a quick second click)
    button.classList.add("is-flaring");
    setTimeout(function () { button.classList.remove("is-flaring"); }, 500);
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest(FLARED);
    if (!button || button.disabled || button.matches(CALM)) return;
    if (!reduceMotion) flare(button);
    if (button.matches(".wm-button, .wm-compose, .wm-icon[data-act], [data-wm-busy]")) pressed = { button: button, at: Date.now() };
  }, true);
  function spinnerFor(method) {
    if (method === "GET" || !pressed || Date.now() - pressed.at > 800 || !pressed.button.isConnected) return null;
    var button = pressed.button;
    pressed = null;
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    return button;
  }
  function stopSpinner(button) {
    if (!button) return;
    button.classList.remove("is-busy");
    button.removeAttribute("aria-busy");
  }

  // --- menus: the three dots, a right-click ---
  var openMenu = null;

  function closeMenus() {
    if (!openMenu) return;
    var menu = openMenu;
    openMenu = null;
    menu.close();
  }

  // where a box of this size goes at (x, y): inside the window, flipped when it wouldn't fit
  function place(x, y, width, height) {
    var roomX = window.innerWidth, roomY = window.innerHeight;
    function fit(at, size, room) {
      if (at + size <= room - 8) return at;
      if (at - size >= 8) return at - size;
      return Math.max(8, room - size - 8);
    }
    return { x: fit(x, width, roomX), y: fit(y, height, roomY) };
  }

  function positionAt(box, at, side) {
    var rect;
    if (at && at.getBoundingClientRect) {
      rect = at.getBoundingClientRect();
    } else {
      rect = { left: at.x, right: at.x, top: at.y, bottom: at.y };
    }
    var width = box.offsetWidth, height = box.offsetHeight;
    var spot;
    if (side === "right") {   // a submenu: beside the item
      spot = { x: rect.right + 4, y: rect.top - 8 };
      if (spot.x + width > window.innerWidth - 8) spot.x = rect.left - width - 4;
      spot.y = Math.min(spot.y, window.innerHeight - height - 8);
      spot.x = Math.max(8, spot.x);
      spot.y = Math.max(8, spot.y);
    } else if (at && at.getBoundingClientRect) {   // under the button, its right edges lined up
      spot = { x: rect.right - width, y: rect.bottom + 6 };
      if (spot.x < 8) spot.x = rect.left;
      if (spot.y + height > window.innerHeight - 8) spot.y = Math.max(8, rect.top - height - 6);
      spot.x = Math.max(8, Math.min(spot.x, window.innerWidth - width - 8));
    } else {
      spot = place(rect.left, rect.top, width, height);
    }
    box.style.left = spot.x + "px";
    box.style.top = spot.y + "px";
  }

  function menu(at, items, options) {
    closeMenus();
    options = options || {};
    var mask = document.createElement("div");
    mask.className = "wm-menu-mask";
    var box = document.createElement("div");
    box.className = "wm-menu-pop";
    box.setAttribute("role", "menu");
    var sub = null;   // an open submenu (the folder picker)

    items.filter(function (item) { return item && !item.hidden; }).forEach(function (item, index, shown) {
      if (item === "-") {
        if (index === 0 || index === shown.length - 1 || shown[index - 1] === "-") return;
        var line = document.createElement("hr");
        line.className = "wm-menu-line";
        box.appendChild(line);
        return;
      }
      var button = document.createElement("button");
      button.type = "button";
      button.className = "wm-menu-item" + (item.danger ? " is-danger" : "");
      button.setAttribute("role", item.switchOn !== undefined ? "menuitemcheckbox" : "menuitem");
      if (item.switchOn !== undefined) button.setAttribute("aria-checked", String(!!item.switchOn));
      if (item.icon) button.appendChild(icon(item.icon));
      var label = document.createElement("span");
      label.className = "wm-menu-label";
      label.textContent = item.label;
      button.appendChild(label);
      if (item.switchOn !== undefined) {
        var knob = document.createElement("span");
        knob.className = "wm-switch wm-menu-switch";
        knob.innerHTML = "<span></span>";
        button.appendChild(knob);
      }
      if (item.submenu) {
        button.setAttribute("aria-haspopup", "true");
        button.appendChild(icon("chevron-right")).classList.add("wm-menu-trail");
      }
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        if (item.submenu) {
          openSub(button, item);
          return;
        }
        close();
        if (item.act) item.act();
      });
      if (item.submenu) {
        button.addEventListener("mouseenter", function () { openSub(button, item); });
      } else {
        button.addEventListener("mouseenter", function () { closeSub(); });
      }
      box.appendChild(button);
    });

    function openSub(button, item) {
      if (sub && sub.owner === button) return;
      closeSub();
      sub = item.submenu(button);
      if (sub) sub.owner = button;
    }
    function closeSub() {
      if (sub) sub.close();
      sub = null;
    }

    function close() {
      closeSub();
      mask.remove();
      box.classList.add("is-leaving");
      setTimeout(function () { box.remove(); }, reduceMotion ? 0 : 120);
      document.removeEventListener("keydown", keys, true);
      window.removeEventListener("resize", close);
      if (openMenu === handle) openMenu = null;
      if (options.onClose) options.onClose();
      if (at && at.focus && box.contains(document.activeElement)) at.focus();
    }

    function focusables() {
      return Array.prototype.slice.call(box.querySelectorAll(".wm-menu-item"));
    }
    function keys(event) {
      if (sub && sub.box && sub.box.contains(document.activeElement)) return;   // the submenu's own
      var list = focusables();
      var at = list.indexOf(document.activeElement);
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        var step = event.key === "ArrowDown" ? 1 : -1;
        var next = list[(at + step + list.length) % list.length];
        if (next) next.focus();
      } else if (event.key === "ArrowRight" && list[at] && list[at].getAttribute("aria-haspopup")) {
        event.preventDefault();
        list[at].click();
      } else if (event.key === "Tab") {
        close();
      }
    }

    mask.addEventListener("mousedown", function (event) { event.preventDefault(); close(); });
    mask.addEventListener("contextmenu", function (event) { event.preventDefault(); close(); });
    document.body.appendChild(mask);
    document.body.appendChild(box);
    positionAt(box, at, options.side);
    document.addEventListener("keydown", keys, true);
    window.addEventListener("resize", close);
    document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: {} }));
    var first = box.querySelector(".wm-menu-item");
    if (first && options.focus !== false) first.focus({ preventScroll: true });
    var handle = { close: close, box: box };
    openMenu = handle;
    return handle;
  }

  // --- the dialog that asks first ---
  function confirmDialog(options) {
    return new Promise(function (resolve) {
      var dialog = document.createElement("dialog");
      dialog.className = "wm-dialog";
      dialog.innerHTML = '<form method="dialog" class="wm-dialog-card">' +
        '<h2 class="wm-dialog-title"></h2><p class="wm-dialog-text"></p>' +
        '<div class="wm-dialog-actions"><button type="button" class="wm-button is-ghost" value="no"></button>' +
        '<button type="submit" class="wm-button" value="yes"></button></div></form>';
      dialog.querySelector(".wm-dialog-title").textContent = options.title;
      var text = dialog.querySelector(".wm-dialog-text");
      if (options.text) text.textContent = options.text;
      else text.remove();
      var no = dialog.querySelector('[value="no"]');
      var yes = dialog.querySelector('[value="yes"]');
      no.textContent = options.no || "Cancel";
      yes.textContent = options.yes || "OK";
      if (options.danger) yes.classList.add("is-danger");
      var answered = false;
      function done(value) {
        if (answered) return;
        answered = true;
        dialog.classList.add("is-leaving");
        setTimeout(function () {
          if (dialog.open) dialog.close();
          dialog.remove();
        }, reduceMotion ? 0 : 160);
        resolve(value);
      }
      no.addEventListener("click", function () { done(false); });
      dialog.querySelector("form").addEventListener("submit", function (event) {
        event.preventDefault();
        done(true);
      });
      dialog.addEventListener("cancel", function (event) {
        event.preventDefault();
        done(false);
      });
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) done(false);   // the backdrop
      });
      document.body.appendChild(dialog);
      closeMenus();
      dialog.showModal();
      yes.focus();
    });
  }

  // --- the folders, as the side column has them ---
  function folders() {
    return Array.prototype.map.call(document.querySelectorAll("[data-wm-folders] .wm-folder"), function (row) {
      return {
        key: row.dataset.folder, name: row.dataset.name, role: row.dataset.role, root: row.dataset.root,
        depth: Number(row.dataset.depth || 0), menu: (row.dataset.menu || "").split(" "), row: row,
        parent: row.parentElement.parentElement.closest(".wm-folder-item") ?
          row.parentElement.parentElement.closest(".wm-folder-item").querySelector(".wm-folder").dataset.folder : null,
      };
    });
  }

  var FOLDER_ICONS = { inbox: "inbox", drafts: "drafts", sent: "sent", archive: "archive", junk: "spam", trash: "trash" };

  // The folder picker, as PrivateEmail's: a search field, the folders as a tree (the folders in
  // one fold open with its arrow; all of them while searching), the folder they're in picked out,
  // and with create: a folder can be made inside one there and then (its "+"), and chosen.
  function pickFolder(at, options) {
    options = options || {};
    return new Promise(function (resolve) {
      var all = folders().filter(function (folder) {
        return options.all || (folder.role !== "drafts" && folder.role !== "sent");
      });
      var chosen = false;
      var expanded = {};
      var current = options.current;
      var here = all.filter(function (folder) { return folder.key === current; })[0];
      while (here && here.parent) {   // the folder they're in: its folders opened out to it
        expanded[here.parent] = true;
        here = all.filter(function (folder) { return folder.key === here.parent; })[0];
      }
      var box = document.createElement("div");
      box.className = "wm-menu-pop wm-picker";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-label", options.title || "Move to folder");
      box.innerHTML = '<p class="wm-picker-title"></p><label class="wm-picker-search"><span class="visually-hidden">Search folders</span>' +
        '<input type="search" placeholder="Search folders" autocomplete="off"></label><ul class="wm-picker-list" role="listbox"></ul>';
      box.querySelector(".wm-picker-title").textContent = options.title || "Move to folder";
      box.querySelector(".wm-picker-search").insertBefore(icon("search"), box.querySelector(".wm-picker-search input"));
      var input = box.querySelector("input");
      var list = box.querySelector(".wm-picker-list");
      var mask = null;
      if (!options.nested) {
        mask = document.createElement("div");
        mask.className = "wm-menu-mask";
        mask.addEventListener("mousedown", function (event) { event.preventDefault(); close(null); });
        document.body.appendChild(mask);
      }

      function kids(key) {
        return all.filter(function (folder) { return folder.parent === key; });
      }
      function hasKids(key) {
        return folders().some(function (folder) { return folder.parent === key; });
      }
      function matches(folder, words) {
        if (!words) return true;
        if (folder.name.toLowerCase().indexOf(words) >= 0) return true;
        return kids(folder.key).some(function (kid) { return matches(kid, words); });
      }
      function draw() {
        var words = input.value.trim().toLowerCase();
        list.innerHTML = "";
        function add(folder, level) {
          if (!matches(folder, words)) return;
          var open = words ? true : !!expanded[folder.key];
          var item = document.createElement("li");
          item.className = "wm-picker-item" + (folder.key === current ? " is-current" : "");
          item.setAttribute("role", "option");
          item.setAttribute("aria-selected", String(folder.key === current));
          item.tabIndex = -1;
          item.dataset.key = folder.key;
          var label = document.createElement("span");
          label.className = "wm-picker-label";
          label.style.paddingInlineStart = level * 16 + "px";
          if (kids(folder.key).length) {
            var opener = document.createElement("button");
            opener.type = "button";
            opener.className = "wm-picker-opener" + (open ? " is-open" : "");
            opener.setAttribute("aria-label", open ? "Collapse" : "Expand");
            opener.tabIndex = -1;
            opener.appendChild(icon("chevron-right"));
            opener.addEventListener("click", function (event) {
              event.stopPropagation();
              expanded[folder.key] = !open;
              draw();
            });
            label.appendChild(opener);
          } else {
            var spacer = document.createElement("span");
            spacer.className = "wm-picker-spacer";
            label.appendChild(spacer);
          }
          if (FOLDER_ICONS[folder.role]) label.appendChild(icon(FOLDER_ICONS[folder.role]));
          var name = document.createElement("span");
          name.className = "wm-picker-name";
          name.textContent = folder.name;
          label.appendChild(name);
          item.appendChild(label);
          if (options.create && folder.menu.indexOf("subfolder") >= 0) {
            var plus = document.createElement("button");
            plus.type = "button";
            plus.className = "wm-picker-create";
            plus.title = "Create subfolder";
            plus.setAttribute("aria-label", "Create subfolder in " + folder.name);
            plus.appendChild(icon("folder-plus"));
            plus.addEventListener("click", function (event) {
              event.stopPropagation();
              createIn(item, folder);
            });
            item.appendChild(plus);
          }
          item.addEventListener("click", function () { close(folder.key); });
          list.appendChild(item);
          if (open) kids(folder.key).forEach(function (kid) { add(kid, level + 1); });
        }
        all.filter(function (folder) { return !folder.parent || !all.some(function (other) { return other.key === folder.parent; }); })
          .forEach(function (folder) { add(folder, 0); });
        if (!list.children.length) {
          var none = document.createElement("li");
          none.className = "wm-picker-none";
          none.textContent = "No folders found";
          list.appendChild(none);
        }
      }

      // a new folder, named in a field right under the folder it goes in; made, it's the one chosen
      function createIn(item, parent) {
        var old = list.querySelector(".wm-picker-new");
        if (old) old.remove();
        var row = document.createElement("li");
        row.className = "wm-picker-new";
        var form = document.createElement("form");
        var field = document.createElement("input");
        field.type = "text";
        field.maxLength = 60;
        field.placeholder = "Folder name";
        field.setAttribute("aria-label", "Folder name");
        var problem = document.createElement("p");
        problem.className = "wm-picker-problem";
        problem.hidden = true;
        form.appendChild(field);
        form.appendChild(problem);
        row.appendChild(form);
        item.after(row);
        field.focus();
        var busy = false;
        form.addEventListener("submit", function (event) {
          event.preventDefault();
          if (busy) return;
          busy = true;
          request(document.querySelector("[data-wm-shell]").dataset.createUrl, {
            method: "POST", body: { name: field.value, parent: parent.key, current: currentFolder() }, quiet: true,
          }).then(function (answer) {
            document.dispatchEvent(new CustomEvent("wm:folders", { detail: answer }));
            close(answer.key);
          }, function (error) {
            busy = false;
            problem.textContent = error.problem || "The folder wasn't made.";
            problem.hidden = false;
            field.focus();
          });
        });
        field.addEventListener("keydown", function (event) {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            row.remove();
          }
        });
      }

      function close(key) {
        if (chosen) return;
        chosen = true;
        if (mask) mask.remove();
        box.remove();
        document.removeEventListener("keydown", keys, true);
        resolve(key);
      }
      function keys(event) {
        if (!box.contains(document.activeElement) && document.activeElement !== document.body) return;
        var items = Array.prototype.slice.call(list.querySelectorAll(".wm-picker-item"));
        var at = items.indexOf(document.activeElement);
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          close(null);
        } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          var next = items[at + (event.key === "ArrowDown" ? 1 : -1)] || (event.key === "ArrowDown" ? items[0] : input);
          next.focus();
        } else if (event.key === "Enter" && at >= 0) {
          event.preventDefault();
          close(items[at].dataset.key);
        } else if (event.key === "ArrowLeft" && options.nested && at >= 0) {
          event.preventDefault();
          close(null);
        }
      }
      input.addEventListener("input", draw);
      draw();
      document.body.appendChild(box);
      positionAt(box, at, options.nested ? "right" : undefined);
      document.addEventListener("keydown", keys, true);
      input.focus({ preventScroll: true });
      if (options.handle) options.handle({ close: function () { close(null); }, box: box });
    });
  }

  function currentFolder() {
    var nav = document.querySelector("[data-wm-folders]");
    return nav ? nav.dataset.current : "";
  }

  // --- the counts ---
  var baseTitle = document.title.replace(/^\(\d+\)\s*/, "");

  function counts(values, unread) {
    if (values) {
      document.querySelectorAll("[data-wm-folders] .wm-folder").forEach(function (row) {
        var count = values[row.dataset.folder];
        if (count === undefined) return;
        var badge = row.querySelector(".wm-count");
        badge.textContent = count > 999 ? "999+" : String(count);
        badge.hidden = !count;
      });
    }
    if (typeof unread === "number") {
      document.title = (unread ? "(" + unread + ") " : "") + baseTitle;
      document.dispatchEvent(new CustomEvent("wm:unread", { detail: unread }));
    }
  }
  function setTitle(title) {
    baseTitle = title;
    var match = document.title.match(/^\((\d+)\)\s*/);
    document.title = (match ? match[0] : "") + title;
  }

  window.wm = {
    request: request, toast: toast, board: board, icon: icon, copy: copy, loading: loading, spinner: spinner, menu: menu,
    closeMenus: closeMenus,
    confirm: confirmDialog, pickFolder: pickFolder, folders: folders, counts: counts, setTitle: setTitle,
    currentFolder: currentFolder, reduceMotion: reduceMotion,
  };
})();
