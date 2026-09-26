// Sends the login forms in the background instead of reloading the page. After a wrong
// password a red notice board drops in with the reason (board.js), and both fields keep
// what was typed (the password stays hidden), so it can be corrected instead of typed
// again. The server never sends the password back.
// With two-factor authentication on, the right password brings up the PIN form in its
// place; six digits send the PIN by themselves. Without JavaScript the forms post the
// normal way and the error shows on the page.
(function () {
  var form = document.querySelector("[data-login-form]");
  var pinForm = document.querySelector("[data-pin-form]");
  var inlineError = document.querySelector("[data-login-error]");
  if (!form || !window.fetch) return;
  var password = form.querySelector("input[name=password]");
  var pin = pinForm && pinForm.querySelector("input[name=pin]");

  // Back in a field, cursor at the end, ready to fix a typo.
  function returnTo(input) {
    input.focus();
    var end = input.value.length;
    try {
      input.setSelectionRange(end, end);
    } catch (error) {
      // some browsers don't allow moving the cursor in password fields; focus is enough
    }
  }

  function showError(sent, message) {
    sent.dispatchEvent(new Event("someless:done")); // its button stops spinning
    if (window.somelessBoard) {
      window.somelessBoard.show({ type: "error", title: "Couldn't log you in", message: message });
    } else if (inlineError) {
      inlineError.textContent = message;
      inlineError.hidden = false;
    }
  }

  // One step of the login in place of the other, sliding in.
  function showStep(showing, hiding) {
    hiding.hidden = true;
    showing.hidden = false;
    showing.classList.remove("is-entering");
    void showing.offsetWidth; // restart the slide
    showing.classList.add("is-entering");
  }

  function send(sent, url, answered) {
    if (inlineError) inlineError.hidden = true;
    fetch(url, {
      method: "POST",
      body: new FormData(sent),
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().catch(function () { return null; }).then(function (data) {
          if (!data) {
            // not a login answer, e.g. the form's security token expired
            showError(sent, "This page has expired. Reload it and try again.");
          } else if (response.ok && data.redirect) {
            window.location.assign(data.redirect);
          } else {
            answered(data);
          }
        });
      })
      .catch(function () {
        showError(sent, "Can't reach the server. Check your connection and try again.");
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    send(form, form.action || window.location.href, function (data) {
      if (data.pin && pinForm) {
        form.dispatchEvent(new Event("someless:done"));
        pin.value = "";
        showStep(pinForm, form);
        pin.focus();
        return;
      }
      showError(form, data.error || "Something went wrong. Try again.");
      returnTo(password);
    });
  });

  if (!pinForm) return;

  pinForm.addEventListener("submit", function (event) {
    event.preventDefault();
    send(pinForm, pinForm.action, function (data) {
      showError(pinForm, data.error || "Something went wrong. Try again.");
      if (data.restart) {
        // the password has to be checked again first (took too long, or too many tries)
        showStep(form, pinForm);
        returnTo(password);
      } else {
        pin.select();
      }
    });
  });

  // Just the digits, and six of them send the PIN straight away.
  pin.addEventListener("input", function () {
    var digits = pin.value.replace(/\D/g, "").slice(0, 6);
    if (pin.value !== digits) pin.value = digits;
    if (digits.length === 6 && !pinForm.querySelector("[aria-busy='true']")) pinForm.requestSubmit();
  });

  pinForm.querySelector("[data-pin-back]").addEventListener("click", function () {
    showStep(form, pinForm);
    returnTo(password);
  });
})();
