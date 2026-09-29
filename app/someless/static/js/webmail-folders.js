// The webmail's folders (webmail-mail.html, webmail-folders.html), as PrivateEmail has them. Each
// folder's menu (its three dots, or a right-click) offers what suits it (folders.py): Create
// subfolder and Rename (a field right in the list: Enter keeps it, Escape leaves it), moving it
// or all its messages to the Archive or the Inbox, marking all read or unread, deleting all its
// messages, deleting it, emptying the Trash (each of those asks first), and "Sort alphabetically".
// The arrow beside a folder folds its folders away, and it stays so. Messages dragged onto a
// folder move there; one of the mailbox's own folders dragged onto another goes inside it.
// Everything goes to mail.py (/folders), which sends the folders back as they are now.
(function () {
  var shell = document.querySelector("[data-wm-shell]");
  var nav = document.querySelector("[data-wm-folders]");
  if (!shell || !nav || !window.wm) return;

  function current() {
    return nav.dataset.current;
  }
  function rowOf(key) {
    return nav.querySelector('.wm-folder[data-folder="' + CSS.escape(key) + '"]');
  }
  function folderUrl(key) {
    return shell.dataset.folderUrl.replace("__key__", encodeURIComponent(key));
  }

  // the folders as they are now (mail.py sends them after each change)
  function redraw(answer) {
    if (answer.html) {
      nav.innerHTML = answer.html;
      nav.classList.add("is-redrawn");
    }
    wm.counts(answer.counts, answer.unread);
  }
  document.addEventListener("wm:folders", function (event) { redraw(event.detail); });

  function run(key, action, extra, options) {
    options = options || {};
    var body = Object.assign({ action: action, current: current() }, extra || {});
    var row = rowOf(key);
    if (row) row.classList.add("is-busy");
    return wm.request(folderUrl(key), { method: "POST", body: body, quiet: options.quiet, failTitle: options.failTitle })
      .then(function (answer) {
        if (row) row.classList.remove("is-busy");
        if (answer.gone) {   // the folder being shown went: to the Inbox
          var inbox = rowOf("inbox") ? rowOf("inbox").querySelector(".wm-folder-link").href : "/";
          if (answer.message) wm.toast(answer.message, { warning: !!answer.warning });
          if (wm.go) wm.go(inbox);
          else location.href = inbox;
          return answer;
        }
        redraw(answer);
        if (answer.message) wm.toast(answer.message, { warning: !!answer.warning });
        if (options.touchesList && wm.list && !answer.warning) wm.list.reload();
        return answer;
      }, function (error) {
        if (row) row.classList.remove("is-busy");
        throw error;
      });
  }

  // is the folder shown in the list this one, or inside it?
  function showsInside(key) {
    var here = current();
    if (!here) return false;
    if (here === key) return true;
    var row = rowOf(here);
    while (row) {
      var parent = row.closest(".wm-subfolders");
      row = parent ? parent.parentElement.querySelector(":scope > .wm-folder") : null;
      if (row && row.dataset.folder === key) return true;
    }
    return false;
  }

  // --- a name typed right in the list: a new folder, or a new name ---
  function nameField(options) {
    var form = document.createElement("form");
    form.className = "wm-folder-form" + (options.creating ? " is-creating" : "");
    form.style.setProperty("--depth", options.depth);
    var field = document.createElement("input");
    field.type = "text";
    field.maxLength = 60;
    field.placeholder = "Folder name";
    field.value = options.value || "";
    field.setAttribute("aria-label", options.creating ? "New folder's name" : "Folder name");
    var tip = document.createElement("p");
    tip.className = "wm-folder-problem";
    tip.setAttribute("role", "alert");
    tip.hidden = true;
    form.appendChild(field);
    form.appendChild(tip);
    var done = false;
    var busy = false;
    function finish() {
      if (done) return;
      done = true;
      form.remove();
      if (options.onGone) options.onGone();
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (busy) return;
      var name = field.value.trim();
      if (!options.creating && name === options.value) {
        finish();
        return;
      }
      busy = true;
      options.save(name).then(function () {
        done = true;   // (the folders were drawn again: the form went with them)
      }, function (error) {
        busy = false;
        tip.textContent = error.problem || "The folder wasn't saved.";
        tip.hidden = false;
        field.focus();
      });
    });
    field.addEventListener("input", function () { tip.hidden = true; });
    field.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        finish();
      }
    });
    field.addEventListener("blur", function () {
      setTimeout(function () {   // (a click on its own tip, or the answer on its way: not yet)
        if (!busy && !form.contains(document.activeElement)) finish();
      }, 150);
    });
    return { form: form, field: field };
  }

  function createIn(key) {
    var row = rowOf(key);
    if (!row) return;
    var item = row.parentElement;
    if (item.classList.contains("is-collapsed")) fold(item, false);
    var made = nameField({
      creating: true, depth: Number(row.dataset.depth) + 1,
      save: function (name) {
        return wm.request(shell.dataset.createUrl, { method: "POST", body: { name: name, parent: key, current: current() }, quiet: true })
          .then(function (answer) { redraw(answer); });
      },
    });
    row.after(made.form);
    made.field.focus();
  }

  function rename(key) {
    var row = rowOf(key);
    if (!row) return;
    var link = row.querySelector(".wm-folder-link");
    row.classList.add("is-renaming");
    var made = nameField({
      value: row.dataset.name, depth: Number(row.dataset.depth),
      save: function (value) {
        return run(key, "rename", { name: value }, { quiet: true });
      },
      onGone: function () { row.classList.remove("is-renaming"); },
    });
    link.after(made.form);
    made.field.focus();
    made.field.select();
  }

  // --- the menu ---
  var TRASH_TEXT = "You can recover messages moved to Trash later if you change your mind.";

  function menuFor(row, at) {
    var key = row.dataset.folder;
    var name = row.dataset.name;
    var offers = (row.dataset.menu || "").split(" ");
    var inTrash = row.dataset.root === "trash";
    function has(item) { return offers.indexOf(item) >= 0; }
    row.classList.add("is-menu");
    wm.menu(at, [
      { label: "Create subfolder", icon: "folder-plus", hidden: !has("subfolder"), act: function () { createIn(key); } },
      { label: "Rename", icon: "edit", hidden: !has("rename"), act: function () { rename(key); } },
      { label: "Move all to Archive", icon: "archive", hidden: !has("archive_all"),
        act: function () { run(key, "archive_all", null, { touchesList: showsInside(key) }); } },
      { label: "Move folder to Archive", icon: "move", hidden: !has("to_archive"), act: function () { run(key, "to_archive"); } },
      { label: "Move all to Inbox", icon: "inbox", hidden: !has("inbox_all"),
        act: function () { run(key, "inbox_all", null, { touchesList: showsInside(key) }); } },
      { label: "Move folder to Inbox", icon: "move", hidden: !has("to_inbox"), act: function () { run(key, "to_inbox"); } },
      "-",
      { label: "Mark all as read", icon: "read", hidden: !has("read_all"),
        act: function () { run(key, "read_all", null, { touchesList: showsInside(key) }); } },
      { label: "Mark all as unread", icon: "unread", hidden: !has("unread_all"),
        act: function () { run(key, "unread_all", null, { touchesList: showsInside(key) }); } },
      "-",
      { label: "Delete all messages", icon: "trash", hidden: !has("delete_all"), act: function () {
        wm.confirm(inTrash ? {
          title: "Delete all messages in folder?", text: "Are you sure you want to permanently delete all messages?",
          yes: "Yes, permanently delete", no: "No, don’t delete", danger: true,
        } : { title: "Move to Trash?", text: TRASH_TEXT, yes: "Move to Trash", no: "Cancel", danger: true }).then(function (yes) {
          if (yes) run(key, "delete_all", null, { touchesList: showsInside(key) });
        });
      } },
      { label: "Delete folder", icon: "trash", hidden: !has("delete"), act: function () {
        wm.confirm(inTrash ? {
          title: "Delete \"" + name + "\" folder?", text: "Are you sure you want to permanently delete this folder?",
          yes: "Yes, permanently delete", no: "No, don’t delete", danger: true,
        } : {
          title: "Move \"" + name + "\" to Trash?", text: "You can recover this folder later if you change your mind.",
          yes: "Move to Trash", no: "Cancel", danger: true,
        }).then(function (yes) {
          if (yes) run(key, "delete");
        });
      } },
      { label: "Empty folder", icon: "trash", hidden: !has("empty"), act: function () {
        wm.confirm({
          title: "Empty Folder?", text: "The contents of the Trash folder will be deleted permanently.",
          yes: "Yes, permanently delete", no: "No, don’t delete", danger: true,
        }).then(function (yes) {
          if (yes) run(key, "empty", null, { touchesList: showsInside(key) });
        });
      } },
      "-",
      { label: "Sort alphabetically", icon: "sort", switchOn: nav.dataset.byName === "1", act: sortByName },
    ], { onClose: function () { row.classList.remove("is-menu"); } });
  }

  function sortByName() {
    var on = nav.dataset.byName !== "1";
    wm.request(shell.dataset.orderUrl, { method: "POST", body: { by_name: on, current: current() } }).then(function (answer) {
      nav.dataset.byName = answer.by_name ? "1" : "0";
      redraw(answer);
    });
  }

  // --- folding a folder's folders away ---
  function fold(item, folded) {
    var opener = item.querySelector(":scope > .wm-folder > .wm-folder-opener");
    item.classList.toggle("is-collapsed", folded);
    if (opener) opener.setAttribute("aria-expanded", String(!folded));
    var key = item.querySelector(":scope > .wm-folder").dataset.folder;
    run(key, folded ? "collapse" : "expand", null, { quiet: true }).catch(function () {});
  }

  nav.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-wm-fold]");
    if (opener) {
      event.preventDefault();
      var item = opener.closest(".wm-folder-item");
      fold(item, !item.classList.contains("is-collapsed"));
      return;
    }
    var dots = event.target.closest("[data-wm-folder-menu]");
    if (dots) {
      event.preventDefault();
      menuFor(dots.closest(".wm-folder"), dots);
      return;
    }
    var link = event.target.closest(".wm-folder-link");
    if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) {
      // picked out at once, while its page comes
      nav.querySelectorAll(".wm-folder.is-current").forEach(function (row) { row.classList.remove("is-current"); });
      link.closest(".wm-folder").classList.add("is-current");
    }
  });
  nav.addEventListener("contextmenu", function (event) {
    var row = event.target.closest(".wm-folder");
    if (!row || event.shiftKey || row.classList.contains("is-renaming")) return;
    event.preventDefault();
    menuFor(row, row.querySelector("[data-wm-folder-menu]"));
  });

  // --- dropping messages, or a folder, onto a folder ---
  var MESSAGES = "application/x-wm-messages", FOLDER = "application/x-wm-folder";
  var dragged = null;   // the folder being dragged: its key

  function takes(row, types) {
    if (!row) return false;
    if (types.indexOf(MESSAGES) >= 0) {
      return row.dataset.role !== "drafts" && row.dataset.role !== "sent" && row.dataset.folder !== current();
    }
    if (types.indexOf(FOLDER) >= 0 && dragged) {
      if (row.dataset.folder === dragged) return false;
      if ((row.dataset.menu || "").indexOf("subfolder") < 0) return false;
      var from = rowOf(dragged);
      if (!from || from.parentElement.contains(row)) return false;   // not inside itself
      var parent = from.parentElement.parentElement.closest(".wm-folder-item");
      return !(parent && parent.querySelector(":scope > .wm-folder") === row);   // there already
    }
    return false;
  }

  nav.addEventListener("dragstart", function (event) {
    var row = event.target.closest && event.target.closest(".wm-folder.is-own");
    if (!row) return;
    dragged = row.dataset.folder;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(FOLDER, dragged);
    event.dataTransfer.setData("text/plain", row.dataset.name);
    row.classList.add("is-dragged");
  });
  nav.addEventListener("dragend", function () {
    var row = dragged && rowOf(dragged);
    if (row) row.classList.remove("is-dragged");
    dragged = null;
    nav.querySelectorAll(".is-drop").forEach(function (one) { one.classList.remove("is-drop"); });
  });
  nav.addEventListener("dragover", function (event) {
    var row = event.target.closest(".wm-folder");
    var types = Array.prototype.slice.call(event.dataTransfer.types);
    nav.querySelectorAll(".is-drop").forEach(function (one) { if (one !== row) one.classList.remove("is-drop"); });
    if (!takes(row, types)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    row.classList.add("is-drop");
  });
  nav.addEventListener("dragleave", function (event) {
    var row = event.target.closest(".wm-folder");
    if (row && !row.contains(event.relatedTarget)) row.classList.remove("is-drop");
  });
  nav.addEventListener("drop", function (event) {
    var row = event.target.closest(".wm-folder");
    var types = Array.prototype.slice.call(event.dataTransfer.types);
    if (!takes(row, types)) return;
    event.preventDefault();
    row.classList.remove("is-drop");
    if (types.indexOf(MESSAGES) >= 0) {
      var target = JSON.parse(event.dataTransfer.getData(MESSAGES) || "{}");
      if (wm.actions) wm.actions.move(target, row.dataset.folder);
    } else if (dragged) {
      var key = dragged;
      var name = rowOf(key) ? rowOf(key).dataset.name : "";
      wm.confirm({
        title: "Move \"" + name + "\" folder?", text: "It goes in " + row.dataset.name + ", with everything in it.",
        yes: "Move", no: "Cancel",
      }).then(function (yes) {
        if (yes) run(key, "move", { to: row.dataset.folder });
      });
    }
  });

  window.wm.folderActions = { run: run, createIn: createIn, rename: rename };
})();
