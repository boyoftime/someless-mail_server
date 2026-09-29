// The Signatures page (webmail-settings-signatures.html, settings.py): New signature opens an empty
// one on the right, a signature picked from the list opens it; its name, what it says (the small
// editor, webmail-editor.js), whether it's the default; Save keeps it. Its menu (the three dots)
// makes it the default or deletes it (after asking). Leaving it with changes asks first.
(function () {
  var holder = document.querySelector("[data-wm-signatures]");
  if (!holder || !window.wm || !wm.editor) return;
  var list = holder.querySelector("[data-wm-signature-list]");
  var empty = holder.querySelector("[data-wm-signatures-empty]");
  var panel = holder.querySelector("[data-wm-signature-editor]");
  var form = holder.querySelector("[data-wm-signature-form]");
  var problem = form.querySelector("[data-wm-problem]");
  var url = holder.dataset.url;
  var editing = null;   // the signature open: its id, or "new"
  var changed = false;
  var editor = wm.editor(holder.querySelector("[data-wm-signature-body]"), {
    placeholder: "Start typing your email signature",
    onChange: function () { changed = true; },
  });

  function draw(signatures) {
    list.innerHTML = "";
    signatures.forEach(function (signature) {
      var item = document.createElement("li");
      item.className = "wm-signature-item" + (String(signature.id) === String(editing) ? " is-open" : "");
      item.dataset.id = signature.id;
      item.dataset.name = signature.name;
      item.dataset.default = signature.is_default ? "1" : "0";
      var open = document.createElement("button");
      open.type = "button";
      open.className = "wm-signature-open";
      open.setAttribute("data-wm-open-signature", "");
      var name = document.createElement("span");
      name.className = "wm-signature-name";
      name.textContent = signature.name;
      open.appendChild(name);
      if (signature.is_default) {
        var badge = document.createElement("span");
        badge.className = "wm-badge";
        badge.textContent = "Default";
        open.appendChild(badge);
      }
      var more = document.createElement("button");
      more.type = "button";
      more.className = "wm-icon wm-mini";
      more.setAttribute("data-wm-signature-menu", "");
      more.setAttribute("aria-label", "More options");
      more.appendChild(wm.icon("more"));
      var html = document.createElement("template");
      html.setAttribute("data-html", "");
      html.innerHTML = signature.html;
      item.appendChild(open);
      item.appendChild(more);
      item.appendChild(html);
      list.appendChild(item);
    });
    empty.hidden = signatures.length > 0;
  }

  function leaveOk() {
    if (!changed) return Promise.resolve(true);
    return wm.confirm({ title: "Leave without saving?", text: "You have unsaved changes. If you leave now, your signature will be lost.",
                        yes: "Leave signatures", no: "Cancel" });
  }

  function open(item) {
    leaveOk().then(function (ok) {
      if (!ok) return;
      editing = item ? item.dataset.id : "new";
      list.querySelectorAll(".wm-signature-item").forEach(function (one) { one.classList.toggle("is-open", one === item); });
      form.name.value = item ? item.dataset.name : "";
      form.default.checked = item ? item.dataset.default === "1" : !list.children.length;
      editor.set(item ? item.querySelector("[data-html]").innerHTML : "");
      problem.hidden = true;
      panel.hidden = false;
      changed = false;
      form.name.focus();
    });
  }

  document.querySelectorAll("[data-wm-new-signature]").forEach(function (button) {
    button.addEventListener("click", function () { open(null); });
  });
  list.addEventListener("click", function (event) {
    var item = event.target.closest(".wm-signature-item");
    if (!item) return;
    if (event.target.closest("[data-wm-open-signature]")) {
      open(item);
      return;
    }
    var more = event.target.closest("[data-wm-signature-menu]");
    if (!more) return;
    wm.menu(more, [
      { label: "Edit signature", icon: "edit", act: function () { open(item); } },
      { label: "Default signature", icon: "check", hidden: item.dataset.default === "1", act: function () {
        wm.request(url + "/" + item.dataset.id + "/default", { method: "POST", body: {} }).then(function (answer) {
          draw(answer.signatures);
          wm.toast(answer.message);
        });
      } },
      "-",
      { label: "Delete signature", icon: "trash", danger: true, act: function () {
        wm.confirm({ title: "Delete Signature?", text: 'Are you sure you want to delete the "' + item.dataset.name + '" signature?',
                     yes: "Delete", no: "Cancel", danger: true }).then(function (yes) {
          if (!yes) return;
          wm.request(url + "/" + item.dataset.id + "/delete", { method: "POST", body: {}, failTitle: "Error occured during deleting signature" })
            .then(function (answer) {
              if (String(editing) === item.dataset.id) {
                panel.hidden = true;
                editing = null;
                changed = false;
              }
              draw(answer.signatures);
              wm.toast(answer.message);
            });
        });
      } },
    ]);
  });

  form.querySelector("[data-wm-cancel]").addEventListener("click", function () {
    leaveOk().then(function (ok) {
      if (!ok) return;
      panel.hidden = true;
      editing = null;
      changed = false;
      list.querySelectorAll(".is-open").forEach(function (one) { one.classList.remove("is-open"); });
    });
  });
  form.name.addEventListener("input", function () { changed = true; });
  form.default.addEventListener("change", function () { changed = true; });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    problem.hidden = true;
    var target = editing === "new" ? url : url + "/" + editing;
    wm.request(target, { method: "POST", quiet: true,
                         body: { name: form.name.value, html: editor.html(), default: form.default.checked } })
      .then(function (answer) {
        if (editing === "new" && answer.id) editing = String(answer.id);
        changed = false;
        draw(answer.signatures);
        wm.toast(answer.message);
      }, function (error) {
        problem.textContent = error.problem || "Something went wrong.";
        problem.hidden = false;
      });
  });

  window.addEventListener("beforeunload", function (event) {
    if (!changed) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
