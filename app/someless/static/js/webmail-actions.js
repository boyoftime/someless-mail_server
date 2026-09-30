// What's done to messages in the webmail (webmail-mail.html), as PrivateEmail does it: the boxes
// tick them (Shift ticks a run of them, Ctrl or Cmd one more), and with two or more ticked the
// reading pane shows how many, with what can be done to them all ("Select all" reaches the
// whole folder, past what's loaded). A right-click on a message opens its menu; the reading
// pane's buttons act on the open one; messages can be dragged onto a folder. The keys: the
// arrows open the next or the one before (with Shift, tick them), Shift+I and Shift+U mark read
// and unread, Delete deletes. Each goes to mail.py /do; the toast says what was done, the board
// what went wrong. For the other scripts, as wm.actions: act(action, ids, to), ticked().
(function () {
  var shell = document.querySelector("[data-wm-shell]");
  var section = document.querySelector("[data-wm-list]");
  var list = document.querySelector("[data-wm-messages]");
  var reader = document.querySelector("[data-wm-reader]");
  if (!shell || !section || !list || !reader || !window.wm || !wm.list) return;
  var choose = reader.querySelector("[data-wm-choose]");
  var empty = reader.querySelector("[data-wm-empty]");
  var view = reader.querySelector("[data-wm-view]");
  var count = reader.querySelector("[data-wm-choose-count]");
  function allowedNow() {   // what this list's messages can have done (mail.py)
    try {
      return JSON.parse(section.dataset.actions || "{}");
    } catch (error) {
      return {};
    }
  }
  var everything = false;   // "Select all": the whole folder, past what's loaded
  var anchor = null;        // where a run of ticks (Shift) starts

  function rows() {
    return wm.list.rows();
  }
  function boxOf(row) {
    return row.querySelector("input[type=checkbox]");
  }
  function ticked() {
    return rows().filter(function (row) { return boxOf(row).checked; });
  }
  function idsOf(someRows) {
    return someRows.map(function (row) { return row.dataset.id; });
  }

  // --- the ticks, and the panel for two or more ---
  function showTicks() {
    var chosen = ticked();
    var many = chosen.length > 1;
    if (!chosen.length || (everything && chosen.length < rows().length)) everything = false;
    choose.hidden = !many;
    reader.classList.toggle("is-choosing", many);
    document.body.classList.toggle("is-choosing", many);
    if (many) {
      empty.hidden = true;
      view.hidden = true;
      count.textContent = everything ? wm.list.total() : chosen.length;
      // what the buttons offer follows what's ticked: Mark as read while some are unread, and so on
      var unread = chosen.some(function (row) { return row.dataset.unread === "1"; });
      var read = chosen.some(function (row) { return row.dataset.unread !== "1"; });
      var flagged = chosen.some(function (row) { return row.dataset.flagged === "1"; });
      var unflagged = chosen.some(function (row) { return row.dataset.flagged !== "1"; });
      var when = { unread: unread || everything, read: read || everything, flagged: flagged, unflagged: unflagged || everything };
      choose.querySelectorAll("[data-when]").forEach(function (button) { button.hidden = !when[button.dataset.when]; });
      var all = choose.querySelector("[data-wm-select-all]");
      all.hidden = everything || wm.list.total() <= chosen.length;
    } else {
      view.hidden = !view.dataset.open;
      empty.hidden = !!view.dataset.open;
    }
    list.classList.toggle("has-ticks", chosen.length > 0);
  }

  function untickAll() {
    everything = false;
    rows().forEach(function (row) {
      var box = boxOf(row);
      if (!box.hasAttribute("data-auto")) box.checked = false;
    });
    showTicks();
  }

  function tickRun(from, to) {
    var all = rows();
    var start = all.indexOf(from), end = all.indexOf(to);
    if (start < 0 || end < 0) return;
    if (start > end) {
      var swap = start;
      start = end;
      end = swap;
    }
    for (var index = start; index <= end; index++) {
      boxOf(all[index]).checked = true;
      boxOf(all[index]).removeAttribute("data-auto");
    }
  }

  list.addEventListener("click", function (event) {
    var row = event.target.closest(".wm-message");
    if (!row) return;
    var box = event.target.closest("input[type=checkbox]");
    if (box) {
      box.removeAttribute("data-auto");   // ticked or unticked by hand: it stays when another opens
      if (event.shiftKey && anchor && anchor !== row && anchor.isConnected) tickRun(anchor, row);
      anchor = row;
      showTicks();
      return;
    }
    var link = event.target.closest(".wm-message-link");
    if (!link || event.button !== 0) return;
    if (event.ctrlKey || event.metaKey) {   // one more ticked, or one less
      event.preventDefault();
      var own = boxOf(row);
      own.checked = !own.checked;
      own.removeAttribute("data-auto");
      anchor = row;
      showTicks();
    } else if (event.shiftKey) {   // a run of them
      event.preventDefault();
      tickRun(anchor && anchor.isConnected ? anchor : (list.querySelector(".wm-message.is-open") || row), row);
      anchor = row;
      showTicks();
    }
  });
  // a click on the space around the box ticks it too
  list.addEventListener("click", function (event) {
    var holder = event.target.closest(".wm-check");
    if (holder && event.target === holder) boxOf(holder.closest(".wm-message")).click();
  });

  list.addEventListener("wm:ticks", showTicks);
  list.addEventListener("someless:rows", showTicks);
  document.addEventListener("wm:untick-all", untickAll);

  choose.querySelector("[data-wm-clear]").addEventListener("click", function () {
    everything = false;
    rows().forEach(function (row) { boxOf(row).checked = false; });
    if (wm.reader) wm.reader.close();
    showTicks();
  });
  choose.querySelector("[data-wm-select-all]").addEventListener("click", function () {
    rows().forEach(function (row) {
      boxOf(row).checked = true;
      boxOf(row).removeAttribute("data-auto");
    });
    everything = true;
    showTicks();
  });

  // --- doing it ---
  var doing = false;

  // The messages ticked, for the webmail: their ids, or the whole list ("Select all")
  function selection() {
    if (everything) return { all: { folder: section.dataset.folder, q: section.dataset.q, in: section.dataset.in } };
    return { ids: idsOf(ticked()) };
  }

  function act(action, target, to) {
    if (doing) return Promise.resolve(null);
    var chosen = target || selection();
    if (chosen.ids && !chosen.ids.length) {
      wm.toast("No messages selected", { warning: true });
      return Promise.resolve(null);
    }
    doing = true;
    var body = { action: action, to: to };
    if (chosen.all) body.all = chosen.all;
    else body.ids = chosen.ids;
    reader.classList.add("is-busy");
    return wm.request(shell.dataset.doUrl, { method: "POST", body: body, failTitle: failTitle(action) })
      .then(function (answer) {
        doing = false;
        reader.classList.remove("is-busy");
        wm.counts(answer.counts, answer.unread);
        if (answer.message) wm.toast(answer.message, { warning: !!answer.warning });
        if (answer.warning) return answer;
        var ids = chosen.ids || idsOf(rows());
        if (answer.left) {
          var openId = wm.reader && wm.reader.current();
          if (openId && ids.indexOf(openId) >= 0) wm.reader.close(true);
          everything = false;
          if (chosen.all) {
            wm.list.remove(idsOf(rows()));
            wm.list.refresh({ quiet: true });   // what's left of the folder, if anything
          } else {
            wm.list.remove(ids);
          }
          showTicks();
        } else {
          mark(action, ids);
        }
        return answer;
      }, function () {
        doing = false;
        reader.classList.remove("is-busy");
        return null;
      });
  }

  function failTitle(action) {
    return {
      read: "Couldn't mark as read", unread: "Couldn't mark as unread", flag: "Couldn't mark as favorite",
      unflag: "Couldn't unmark as favorite", archive: "Couldn't move to Archive", inbox: "Couldn't move to Inbox",
      move: "Error occured while moving selected messages", spam: "Error occured while marking message as spam",
      notspam: "Error occured while marking message as not spam", delete: "Error occured. Selected messages has not been deleted",
    }[action] || "That didn't work";
  }

  // read, unread, a favorite or not: the rows and the open message's bar show it
  function mark(action, ids) {
    ids.forEach(function (id) {
      var row = wm.list.rowFor(id);
      if (!row) return;
      if (action === "read" || action === "unread") {
        row.classList.toggle("is-unread", action === "unread");
        row.dataset.unread = action === "unread" ? "1" : "0";
      } else if (action === "flag" || action === "unflag") {
        var on = action === "flag";
        row.classList.toggle("is-flagged", on);
        row.dataset.flagged = on ? "1" : "0";
        var marks = row.querySelector(".wm-preview-line");
        var star = marks.querySelector(".is-star");
        if (on && !star) {
          star = document.createElement("span");
          star.className = "wm-mark is-star";
          star.title = "Favorite";
          star.appendChild(wm.icon("star-filled"));
          marks.appendChild(star);
        } else if (!on && star) {
          star.remove();
        }
      }
    });
    var open = wm.reader && wm.reader.element();
    if (open && ids.indexOf(open.dataset.id) >= 0) flipBar(open, action);
    showTicks();
  }

  // the open message's bar: Mark as read becomes Mark as unread, and so on
  var FLIPS = {
    read: ["unread", "unread", "Mark as unread", ""], unread: ["read", "read", "Mark as read", ""],
    flag: ["unflag", "star-filled", "Unmark as favorite", "is-favorite"], unflag: ["flag", "star", "Mark as favorite", ""],
  };
  function flipBar(open, action) {
    var button = open.querySelector('.wm-read-tools [data-act="' + action + '"]');
    var flip = FLIPS[action];
    if (!button || !flip) return;
    button.dataset.act = flip[0];
    button.replaceChildren(wm.icon(flip[1]));
    button.setAttribute("aria-label", flip[2]);
    button.dataset.tip = flip[2];
    button.classList.toggle("is-favorite", flip[3] === "is-favorite");
    if (action === "read" || action === "unread") open.dataset.unread = action === "unread" ? "1" : "0";
    else open.dataset.flagged = action === "flag" ? "1" : "0";
    document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: { element: button } }));
  }

  function moveTo(target, at) {
    wm.pickFolder(at, { title: "Move to folder", current: section.dataset.folder, create: true }).then(function (key) {
      if (key) act("move", target, key);
    });
  }

  // Disable delete (the panel): nothing but drafts is deleted here; asked (the Delete key), it says why
  var noDelete = shell.hasAttribute("data-no-delete");
  function deleteSome(target) {
    if (noDelete && !allowedNow().drafts) {
      wm.board("Deleting is switched off", "Deleting is switched off for this mailbox by its administrator. " +
               "You can move messages to another folder, like the Archive, instead.");
      return Promise.resolve();
    }
    return act("delete", target);
  }

  // --- the reading pane's buttons, and the panel's ---
  reader.addEventListener("click", function (event) {
    var button = event.target.closest("[data-act]");
    if (!button || button.disabled) return;
    var open = wm.reader && wm.reader.element();
    var inPanel = !!button.closest("[data-wm-choose]");
    var target = inPanel ? selection() : (open ? { ids: [open.dataset.id] } : null);
    if (!target) return;
    var action = button.dataset.act;
    switch (action) {
      case "move":
        moveTo(target, button);
        break;
      case "print":
        window.open(open.dataset.print, "_blank", "noopener");
        break;
      case "download":
        download(open.dataset.download);
        break;
      case "source":
        wm.reader.showSource(open.dataset.source);
        break;
      case "reply": case "reply-all": case "forward": case "edit-draft":
        compose(action, open.dataset.id);
        break;
      default:
        act(action, target);
    }
  });

  function download(url) {
    var link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", "");
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function compose(kind, id) {
    if (window.wm.compose) wm.compose.fromMessage(kind, id);
  }

  // --- the right-click menu, as PrivateEmail's ---
  list.addEventListener("contextmenu", function (event) {
    var row = event.target.closest(".wm-message");
    if (!row || event.shiftKey) return;   // (Shift: the browser's own)
    event.preventDefault();
    var chosenRows = boxOf(row).checked && ticked().length > 1 ? ticked() : [row];
    var target = chosenRows.length > 1 ? selection() : { ids: [row.dataset.id] };
    var single = chosenRows.length === 1;
    var allowed = allowedNow();
    var drafts = allowed.drafts || row.hasAttribute("data-draft");
    var some = function (test) { return everything || chosenRows.some(test); };
    var link = row.querySelector(".wm-message-link");
    row.classList.add("is-menu");
    wm.menu({ x: event.clientX, y: event.clientY }, [
      { label: "Edit draft", icon: "edit", hidden: !(drafts && single), act: function () { compose("edit-draft", row.dataset.id); } },
      { label: "Reply", icon: "reply", hidden: drafts || !single, act: function () { openThen(row, link, "reply"); } },
      { label: "Reply all", icon: "reply-all", hidden: drafts || !single, act: function () { openThen(row, link, "reply-all"); } },
      { label: "Forward", icon: "forward", hidden: drafts || !single, act: function () { openThen(row, link, "forward"); } },
      "-",
      { label: "Mark as read", icon: "read", hidden: drafts || !some(function (r) { return r.dataset.unread === "1"; }), act: function () { act("read", target); } },
      { label: "Mark as unread", icon: "unread", hidden: drafts || !some(function (r) { return r.dataset.unread !== "1"; }), act: function () { act("unread", target); } },
      { label: "Mark as favorite", icon: "star", hidden: drafts || !some(function (r) { return r.dataset.flagged !== "1"; }), act: function () { act("flag", target); } },
      { label: "Unmark as favorite", icon: "star-filled", hidden: drafts || !chosenRows.some(function (r) { return r.dataset.flagged === "1"; }), act: function () { act("unflag", target); } },
      { label: "Move to folder", icon: "move", hidden: drafts, submenu: function (item) {
        var handle = null;
        wm.pickFolder(item, { title: "Move to folder", current: section.dataset.folder, create: true, nested: true,
                              handle: function (made) { handle = made; } })
          .then(function (key) {
            if (!key) return;
            wm.closeMenus();
            act("move", target, key);
          });
        return handle;
      } },
      { label: "Move to Archive", icon: "archive", hidden: !allowed.archive, act: function () { act("archive", target); } },
      { label: "Move to Inbox", icon: "inbox", hidden: !allowed.inbox, act: function () { act("inbox", target); } },
      { label: allowed.not_spam ? "Not spam" : "Mark as spam", icon: allowed.not_spam ? "not-spam" : "spam",
        hidden: !allowed.spam && !allowed.not_spam, act: function () { act(allowed.not_spam ? "notspam" : "spam", target); } },
      { label: "Clear selection", icon: "clear-box", hidden: ticked().filter(function (r) { return !boxOf(r).hasAttribute("data-auto"); }).length === 0,
        act: function () { choose.querySelector("[data-wm-clear]").click(); } },
      "-",
      { label: "Delete", icon: "trash", hidden: noDelete && !allowedNow().drafts, act: function () { deleteSome(target); } },
      "-",
      { label: "Print", icon: "print", hidden: !single, act: function () { window.open(printUrl(row), "_blank", "noopener"); } },
      { label: "Download", icon: "download", hidden: !single, act: function () { download(sourceUrl(row) + "?download=1"); } },
      { label: "View source", icon: "source", hidden: !single, act: function () { wm.reader.showSource(sourceUrl(row)); } },
    ], { onClose: function () { row.classList.remove("is-menu"); } });
  });

  function printUrl(row) {
    return shell.dataset.doUrl.replace(/\/do$/, "/print/") + encodeURIComponent(row.dataset.id);
  }
  function sourceUrl(row) {
    return shell.dataset.doUrl.replace(/\/do$/, "/source/") + encodeURIComponent(row.dataset.id);
  }

  // opened first, then replied to: the reply quotes the message the pane shows
  function openThen(row, link, kind) {
    if (wm.reader.current() === row.dataset.id) {
      compose(kind, row.dataset.id);
      return;
    }
    link.click();
    document.addEventListener("wm:opened", function once(event) {
      document.removeEventListener("wm:opened", once);
      if (event.detail.id === row.dataset.id) compose(kind, row.dataset.id);
    });
  }

  // --- the keys ---
  var cursor = null;   // where the arrow keys are in the list
  document.addEventListener("wm:opened", function () {
    if (cursor) cursor.classList.remove("is-cursor");
    cursor = list.querySelector(".wm-message.is-open");
  });

  function typing(target) {
    return target.closest && target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true'], dialog");
  }
  document.addEventListener("keydown", function (event) {
    if (event.defaultPrevented || typing(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
    if (document.querySelector(".wm-menu-pop")) return;
    var all = rows();
    if (!all.length) return;
    if (!cursor || !cursor.isConnected) cursor = list.querySelector(".wm-message.is-open");
    var at = cursor ? all.indexOf(cursor) : -1;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      var step = event.key === "ArrowDown" ? 1 : -1;
      var next = all[Math.max(0, Math.min(all.length - 1, at + step))];
      if (!next || next === cursor) return;
      event.preventDefault();
      if (event.shiftKey) {   // the next one ticked too, without opening it
        [cursor, next].forEach(function (one) {
          if (!one) return;
          boxOf(one).checked = true;
          boxOf(one).removeAttribute("data-auto");
        });
        showTicks();
      } else {
        next.querySelector(".wm-message-link").click();
      }
      if (cursor) cursor.classList.remove("is-cursor");
      cursor = next;
      if (event.shiftKey) cursor.classList.add("is-cursor");
      next.scrollIntoView({ block: "nearest" });
    } else if (event.shiftKey && (event.key === "I" || event.key === "U")) {
      if (allowedNow().drafts) return;
      event.preventDefault();
      act(event.key === "I" ? "read" : "unread", currentTarget());
    } else if (event.key === "Delete") {
      event.preventDefault();
      deleteSome(currentTarget());
    } else if (event.key === "Escape" && ticked().length > 1) {
      choose.querySelector("[data-wm-clear]").click();
    }
  });

  function currentTarget() {
    var chosen = ticked();
    if (chosen.length > 1) return selection();
    var open = wm.reader && wm.reader.current();
    return { ids: open ? [open] : idsOf(chosen) };
  }

  // --- dragging messages onto a folder (webmail-folders.js takes the drop) ---
  var dragLabel = document.createElement("div");
  dragLabel.className = "wm-drag-label";
  document.body.appendChild(dragLabel);

  list.addEventListener("dragstart", function (event) {
    var row = event.target.closest && event.target.closest(".wm-message");
    if (!row) return;
    var chosenRows = boxOf(row).checked ? ticked() : [row];
    var target = chosenRows.length > 1 ? selection() : { ids: [row.dataset.id] };
    var howMany = target.all ? wm.list.total() : target.ids.length;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-wm-messages", JSON.stringify(target));
    event.dataTransfer.setData("text/plain", howMany + " message(s)");
    dragLabel.textContent = howMany + " message(s)";
    event.dataTransfer.setDragImage(dragLabel, -12, -8);
    chosenRows.forEach(function (one) { one.classList.add("is-dragged"); });
    document.body.classList.add("is-dragging-mail");
  });
  list.addEventListener("dragend", function () {
    list.querySelectorAll(".is-dragged").forEach(function (row) { row.classList.remove("is-dragged"); });
    document.body.classList.remove("is-dragging-mail");
  });

  document.addEventListener("wm:navigated", function () {
    everything = false;
    anchor = null;
    cursor = null;
    showTicks();
  });

  window.wm.actions = {
    act: act, ticked: ticked, selection: selection, untickAll: untickAll, show: showTicks,
    move: function (target, key) { return act("move", target, key); },
  };
  showTicks();
})();
