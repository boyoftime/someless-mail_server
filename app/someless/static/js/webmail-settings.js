// Settings' cards (webmail-settings.html, settings.py): the kinds above them (All, Basic, Email,
// Security), the display name, the keyboard shortcuts, light or dark, the new-mail sound (with a
// way to hear it), the computer's notifications (the browser asks first), and forwarding: an
// address added, changed or deleted, on or off, a copy kept or not. Each goes to the webmail as
// it's changed; the toast says it's done, the board what went wrong. Also the dialogs of Connect
// third-party apps (webmail-settings-apps.html) and the Security Center's new password
// (webmail-settings-security.html).
(function () {
  if (!window.wm) return;

  // --- the kinds ---
  var cards = document.querySelector("[data-wm-cards]");
  document.querySelectorAll("[data-kind].wm-kind").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".wm-kind").forEach(function (other) {
        other.classList.toggle("is-on", other === tab);
        other.setAttribute("aria-selected", String(other === tab));
      });
      cards.querySelectorAll(".wm-card").forEach(function (card) {
        card.hidden = tab.dataset.kind !== "all" && card.dataset.kind !== tab.dataset.kind;
      });
    });
  });

  // --- Profile ---
  var profile = document.querySelector("[data-wm-profile-form]");
  if (profile) {
    profile.addEventListener("submit", function (event) {
      event.preventDefault();
      var problem = profile.querySelector("[data-wm-problem]");
      problem.hidden = true;
      wm.request(location.pathname.replace(/\/$/, "") + "/profile", {
        method: "POST", body: { display_name: profile.display_name.value }, quiet: true,
      }).then(function (answer) {
        wm.toast(answer.message);
        document.querySelector("[data-wm-profile-name]").textContent = answer.display_name;
        profile.display_name.value = answer.display_name;
        var accountName = document.querySelector(".wm-account-name");
        if (accountName) accountName.textContent = answer.display_name;
      }, function (error) {
        problem.textContent = error.problem || "Name update has failed due to a server error.";
        problem.hidden = false;
      });
    });
  }

  function dialogOf(selector) {
    var dialog = document.querySelector(selector);
    if (!dialog) return null;
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog || event.target.closest("[data-wm-close]")) dialog.close();
    });
    return dialog;
  }

  // a button with data-wm-open="name" opens the dialog with data-wm-dialog="name" (Configuration
  // details, on Connect third-party apps)
  document.querySelectorAll("[data-wm-dialog]").forEach(function (dialog) {
    dialogOf('[data-wm-dialog="' + dialog.dataset.wmDialog + '"]');
  });
  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-wm-open]");
    if (!opener) return;
    var dialog = document.querySelector('[data-wm-dialog="' + opener.dataset.wmOpen + '"]');
    if (dialog) dialog.showModal();
  });

  // the IMAP or POP3 half of the configuration (its toggle above it)
  document.querySelectorAll("[data-wm-protocols]").forEach(function (group) {
    group.addEventListener("click", function (event) {
      var option = event.target.closest("[data-value]");
      if (!option) return;
      group.querySelectorAll("[data-value]").forEach(function (other) {
        other.setAttribute("aria-checked", String(other === option));
      });
      group.closest("dialog").querySelectorAll("[data-protocol]").forEach(function (part) {
        part.hidden = part.dataset.protocol !== option.dataset.value;
      });
    });
  });

  var shortcuts = dialogOf("[data-wm-shortcuts-dialog]");
  var shortcutsButton = document.querySelector("[data-wm-shortcuts]");
  if (shortcuts && shortcutsButton) shortcutsButton.addEventListener("click", function () { shortcuts.showModal(); });

  // --- System preferences ---
  document.querySelectorAll("[data-theme-value]").forEach(function (option) {
    option.addEventListener("click", function () {
      var wanted = option.dataset.themeValue;
      var current = document.documentElement.dataset.theme;
      if (wanted !== current) {
        var toggle = document.querySelector("[data-theme-switch]");
        if (toggle) toggle.click();   // (theme.js: the cookie and the page)
      }
      document.querySelectorAll("[data-theme-value]").forEach(function (other) {
        other.setAttribute("aria-checked", String(other.dataset.themeValue === wanted));
      });
    });
  });
  document.addEventListener("someless:theme", function (event) {
    document.querySelectorAll("[data-theme-value]").forEach(function (other) {
      other.setAttribute("aria-checked", String(other.dataset.themeValue === event.detail));
    });
  });

  var sound = document.querySelector("[data-wm-sound]");
  var hear = document.querySelector("[data-wm-hear]");
  if (hear && sound) {
    hear.addEventListener("click", function () {
      sound.currentTime = 0;
      var playing = sound.play();
      if (playing && playing.catch) playing.catch(function () {});
    });
  }

  function setPreference(button, on) {
    return wm.request(location.pathname.replace(/\/$/, "") + "/preferences", {
      method: "POST", body: { name: button.dataset.wmPreference, on: on },
    }).then(function () {
      button.setAttribute("aria-checked", String(on));
    });
  }

  document.querySelectorAll("[data-wm-preference]").forEach(function (button) {
    button.addEventListener("click", function () {
      var on = button.getAttribute("aria-checked") !== "true";
      if (button.dataset.wmPreference === "notifications" && on) {
        if (!window.Notification) {
          wm.board("Notifications aren't there", "This browser can't show them.");
          return;
        }
        Notification.requestPermission().then(function (answer) {
          if (answer !== "granted") {
            wm.board("Notifications are blocked", "Allow them for this site in your browser's settings, then switch them on here.");
            return;
          }
          setPreference(button, true);
        });
        return;
      }
      setPreference(button, on);
    });
  });

  // --- Forwarding ---
  var forwarding = document.querySelector("[data-wm-forwarding]");
  var forwardDialog = dialogOf("[data-wm-forward-dialog]");
  if (forwarding && forwardDialog) {
    var form = forwardDialog.querySelector("[data-wm-forward-form]");
    var problem = form.querySelector("[data-wm-problem]");
    var url = location.pathname.replace(/\/$/, "") + "/forwarding";

    var show = function (state) {
      var has = !!state.address;
      forwarding.dataset.address = state.address || "";
      forwarding.classList.toggle("has-forwarding", has);
      forwarding.querySelector("[data-wm-forwarding-on]").hidden = !has;
      forwarding.querySelector("[data-wm-forwarding-off]").hidden = has;
      forwarding.querySelector("[data-wm-forwarding-add]").hidden = has;
      forwarding.querySelector("[data-wm-forward-address]").textContent = state.address || "";
      forwarding.querySelector('[data-wm-forward-switch="on"]').setAttribute("aria-checked", String(!!state.on));
      forwarding.querySelector('[data-wm-forward-switch="keep"]').setAttribute("aria-checked", String(!!state.keep));
    };

    forwarding.addEventListener("click", function (event) {
      if (event.target.closest("[data-wm-forward-edit]")) {
        var editing = !!forwarding.dataset.address;
        forwardDialog.querySelector("[data-wm-forward-title]").textContent = editing ? "Change the forwarding address" : "Add a forwarding address";
        form.address.value = forwarding.dataset.address;
        problem.hidden = true;
        forwardDialog.showModal();
        form.address.focus();
        return;
      }
      var toggle = event.target.closest("[data-wm-forward-switch]");
      if (toggle) {
        var body = {};
        body[toggle.dataset.wmForwardSwitch] = toggle.getAttribute("aria-checked") !== "true";
        wm.request(url, { method: "POST", body: body, failTitle: "Failed to update forwarding settings." }).then(function (answer) {
          show(answer.forwarding);
        });
        return;
      }
      if (event.target.closest("[data-wm-forward-delete]")) {
        wm.confirm({
          title: "Delete the forwarding address?", text: "Are you sure you want to delete forwarding to " + forwarding.dataset.address + "?",
          yes: "Delete", no: "Cancel", danger: true,
        }).then(function (yes) {
          if (!yes) return;
          wm.request(url + "/delete", { method: "POST", body: {}, failTitle: "Falied to cancel forwarding." }).then(function (answer) {
            show(answer.forwarding);
            wm.toast(answer.message);
          });
        });
      }
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      problem.hidden = true;
      var first = !forwarding.dataset.address;
      wm.request(url, { method: "POST", body: first ? { address: form.address.value, on: true } : { address: form.address.value }, quiet: true })
        .then(function (answer) {
          forwardDialog.close();
          show(answer.forwarding);
          wm.toast(answer.message);
        }, function (error) {
          problem.textContent = error.problem || "Failed to create forwarding.";
          problem.hidden = false;
        });
    });
  }

  // --- Security Center: a new password, its rules ticked off as it's typed; saved, the webmail
  // logs out and the login page asks for it ---
  var passwordForm = document.querySelector("[data-wm-password-form]");
  if (passwordForm) {
    var passwordProblem = passwordForm.querySelector("[data-wm-problem]");
    var fresh = passwordForm.querySelector('[name="password"]');
    var ruleList = passwordForm.querySelector("[data-wm-password-rules]");
    var minLength = Number(ruleList.dataset.minLength) || 8;
    var tests = {
      length: function (value) { return Array.from(value).length >= minLength; },
      letter: function (value) { return /[A-Za-z]/.test(value); },
      number: function (value) { return /[0-9]/.test(value); },
      special: function (value) { return /[^A-Za-z0-9]/.test(value); },
    };
    var tick = function () {
      ruleList.querySelectorAll("[data-rule]").forEach(function (item) {
        var met = !!(tests[item.dataset.rule] && tests[item.dataset.rule](fresh.value));
        item.classList.toggle("is-met", met);
        item.querySelector("[data-state]").textContent = met ? " (done)" : " (not yet)";
      });
    };
    fresh.addEventListener("input", tick);
    tick();
    passwordForm.closest("dialog").addEventListener("close", function () {
      passwordForm.reset();
      passwordProblem.hidden = true;
      tick();
    });
    passwordForm.addEventListener("submit", function (event) {
      event.preventDefault();
      passwordProblem.hidden = true;
      var button = passwordForm.querySelector('[type="submit"]');
      button.disabled = true;
      wm.request(passwordForm.dataset.url, {
        method: "POST", quiet: true,
        body: { current: passwordForm.current.value, password: fresh.value, confirm: passwordForm.confirm.value },
      }).then(function (answer) {
        wm.toast(answer.message);
        setTimeout(function () { location.href = answer.login; }, 1600);
      }, function (error) {
        button.disabled = false;
        passwordProblem.textContent = error.problem || "Your password wasn't changed. Try again.";
        passwordProblem.hidden = false;
      });
    });
  }
})();
