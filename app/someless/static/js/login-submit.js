// Sends the login form in the background instead of reloading the page. After a wrong
// password a red notice board drops in with the reason (board.js), and both fields keep
// what was typed (the password stays hidden), so it can be corrected instead of typed
// again. The server never sends the password back. Without JavaScript the form posts the
// normal way and the error shows on the form itself.
(function () {
  var form = document.querySelector("[data-login-form]");
  var inlineError = document.querySelector("[data-login-error]");
  if (!form || !window.fetch) return;
  var password = form.querySelector("input[name=password]");

  // Back in the password field, cursor at the end, ready to fix a typo.
  function returnToPassword() {
    password.focus();
    var end = password.value.length;
    try {
      password.setSelectionRange(end, end);
    } catch (error) {
      // some browsers don't allow moving the cursor in password fields; focus is enough
    }
  }

  function showError(message) {
    form.dispatchEvent(new Event("someless:done"));
    if (window.somelessBoard) {
      window.somelessBoard.show({ type: "error", title: "Couldn't log you in", message: message });
    } else if (inlineError) {
      inlineError.textContent = message;
      inlineError.hidden = false;
    }
    returnToPassword();
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (inlineError) inlineError.hidden = true;
    fetch(form.action || window.location.href, {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().catch(function () { return null; }).then(function (data) {
          if (!data) {
            // not a login answer, e.g. the form's security token expired
            showError("This page has expired. Reload it and try again.");
          } else if (response.ok && data.redirect) {
            window.location.assign(data.redirect);
          } else {
            showError(data.error || "Something went wrong. Try again.");
          }
        });
      })
      .catch(function () {
        showError("Can't reach the server. Check your connection and try again.");
      });
  });
})();
