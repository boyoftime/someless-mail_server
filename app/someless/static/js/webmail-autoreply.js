// The Auto-reply page (webmail-settings-autoreply.html, settings.py): on or off, when it starts
// and ends, its subject and message (the small editor, webmail-editor.js). Save checks it as
// PrivateEmail does (the dates, a message) and keeps it; Discard changes puts back what was saved.
// Leaving with changes asks first.
(function () {
  var form = document.querySelector("[data-wm-autoreply]");
  if (!form || !window.wm || !wm.editor) return;
  var toggle = form.querySelector("[data-wm-reply-on]");
  var problem = form.querySelector("[data-wm-problem]");
  var saved = form.querySelector("[data-wm-reply-html]").innerHTML;
  var changed = false;
  var editor = wm.editor(form.querySelector("[data-wm-reply-body]"), {
    html: saved, placeholder: "Start typing your auto-reply message", onChange: function () { changed = true; },
  });
  var initial = snapshot();

  function snapshot() {
    return { on: toggle.getAttribute("aria-checked") === "true", start_date: form.start_date.value, start_time: form.start_time.value,
             end_date: form.end_date.value, end_time: form.end_time.value, subject: form.subject.value };
  }
  function showTime() {
    form.querySelector("[data-wm-reply-time]").classList.toggle("is-off", toggle.getAttribute("aria-checked") !== "true");
  }
  showTime();

  toggle.addEventListener("click", function () {
    toggle.setAttribute("aria-checked", String(toggle.getAttribute("aria-checked") !== "true"));
    changed = true;
    showTime();
  });
  form.addEventListener("input", function () { changed = true; });

  form.querySelector("[data-wm-discard]").addEventListener("click", function () {
    toggle.setAttribute("aria-checked", String(initial.on));
    ["start_date", "start_time", "end_date", "end_time", "subject"].forEach(function (name) { form[name].value = initial[name]; });
    editor.set(saved);
    problem.hidden = true;
    changed = false;
    showTime();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    problem.hidden = true;
    var body = snapshot();
    body.html = editor.html();
    wm.request(form.dataset.url, { method: "POST", body: body, quiet: true }).then(function (answer) {
      initial = snapshot();
      saved = body.html;
      changed = false;
      wm.toast(answer.message || "Auto-reply saved");
    }, function (error) {
      problem.textContent = error.problem || "Auto-reply update error";
      problem.hidden = false;
    });
  });

  window.addEventListener("beforeunload", function (event) {
    if (!changed) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
