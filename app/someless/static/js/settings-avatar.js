// Settings > Account > the profile picture (avatar.py). Upload picture picks a file (a JPEG, PNG,
// WebP or GIF up to 5 MB); a dialog shows it behind a circle, to drag into place and zoom (the
// slider, or the mouse wheel). Save sends the file and where the square around the circle is; the
// server cuts it out and keeps it. The picture then shows here and in the top right corner at once.
// Remove takes it away the same way, in the background: the page doesn't move. The webmail's
// Settings > Profile uses it too, for a mailbox's picture: there, the places that show it are marked
// data-avatar-spot (with their letter in data-letter), and its words go on the webmail's toast.
(function () {
  var dialog = document.getElementById("avatar-dialog");
  var choose = document.querySelector("[data-avatar-choose]");
  var file = document.querySelector("[data-avatar-file]");
  if (!dialog || !choose || !file || typeof dialog.showModal !== "function" || !window.fetch) return;
  var form = dialog.querySelector("[data-avatar-form]");
  var stage = dialog.querySelector("[data-avatar-stage]");
  var picture = dialog.querySelector("[data-avatar-image]");
  var zoom = dialog.querySelector("[data-avatar-zoom]");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var LARGEST = 5 * 1024 * 1024;
  var KINDS = ["image/jpeg", "image/png", "image/webp", "image/gif"];
  var chosen = null;   // the file
  var view = { width: 0, height: 0, base: 1, scale: 1, x: 0, y: 0 };   // the picture as shown in the stage

  function board(type, title, message) {
    if (window.wm && type === "error") window.wm.board(title, message);   // (the webmail: errors on its board,
    else if (window.wm) window.wm.toast(message);                         //  what went well on its toast)
    else if (window.somelessBoard) window.somelessBoard.show({ type: type, title: title, message: message });
  }
  var NO_ANSWER = window.wm ? "The webmail didn't answer. Check your connection and try again."
                            : "The panel didn't answer. Check your connection and try again.";

  // the webmail's places for the picture: it, or the letter
  function spots(url) {
    document.querySelectorAll("[data-avatar-spot]").forEach(function (spot) {
      spot.classList.toggle("has-picture", !!url);
      if (url) spot.innerHTML = '<img alt="" src="' + url + '">';
      else spot.textContent = spot.dataset.letter || "";
    });
  }

  function close() {
    if (!dialog.open) return;
    if (reduceMotion) return dialog.close();
    dialog.classList.add("is-closing");
    setTimeout(function () {
      dialog.classList.remove("is-closing");
      dialog.close();
    }, 180);
  }

  function side() { return stage.clientWidth; }

  // keep the picture covering the whole stage, wherever it's dragged
  function draw() {
    var width = view.width * view.scale;
    var height = view.height * view.scale;
    view.x = Math.min(0, Math.max(side() - width, view.x));
    view.y = Math.min(0, Math.max(side() - height, view.y));
    picture.style.width = width + "px";
    picture.style.height = height + "px";
    picture.style.transform = "translate(" + view.x + "px, " + view.y + "px)";
  }

  // zoom around the middle of the stage
  function zoomTo(level) {
    level = Math.min(Number(zoom.max), Math.max(1, level));
    var middle = side() / 2;
    var atX = (middle - view.x) / view.scale;
    var atY = (middle - view.y) / view.scale;
    view.scale = view.base * level;
    view.x = middle - atX * view.scale;
    view.y = middle - atY * view.scale;
    zoom.value = level;
    draw();
  }

  choose.addEventListener("click", function () { file.click(); });
  file.addEventListener("change", function () {
    var picked = file.files[0];
    file.value = "";   // the same file again opens the dialog again
    if (!picked) return;
    if (KINDS.indexOf(picked.type) === -1) return board("error", "Couldn't use the picture", "Choose a JPEG, PNG, WebP or GIF picture.");
    if (picked.size > LARGEST) return board("error", "Couldn't use the picture", "Choose a picture of 5 MB or less.");
    chosen = picked;
    if (picture.src) URL.revokeObjectURL(picture.src);
    picture.onload = function () {
      dialog.showModal();
      view.width = picture.naturalWidth;
      view.height = picture.naturalHeight;
      view.base = side() / Math.min(view.width, view.height);   // the short side fills the circle
      view.scale = view.base;
      view.x = (side() - view.width * view.scale) / 2;         // in the middle, to start with
      view.y = (side() - view.height * view.scale) / 2;
      zoom.value = 1;
      draw();
    };
    picture.onerror = function () { board("error", "Couldn't use the picture", "That file isn't a picture this browser can show."); };
    picture.src = URL.createObjectURL(picked);
  });

  // drag
  var from = null;
  stage.addEventListener("pointerdown", function (event) {
    from = { x: event.clientX - view.x, y: event.clientY - view.y };
    stage.setPointerCapture(event.pointerId);
    stage.classList.add("is-dragging");
  });
  stage.addEventListener("pointermove", function (event) {
    if (!from) return;
    view.x = event.clientX - from.x;
    view.y = event.clientY - from.y;
    draw();
  });
  ["pointerup", "pointercancel"].forEach(function (name) {
    stage.addEventListener(name, function () {
      from = null;
      stage.classList.remove("is-dragging");
    });
  });
  stage.addEventListener("wheel", function (event) {
    event.preventDefault();
    zoomTo(Number(zoom.value) - event.deltaY * 0.0015);
  }, { passive: false });
  zoom.addEventListener("input", function () { zoomTo(Number(zoom.value)); });
  // the arrow keys move it too
  stage.tabIndex = 0;
  stage.addEventListener("keydown", function (event) {
    var step = { ArrowLeft: [10, 0], ArrowRight: [-10, 0], ArrowUp: [0, 10], ArrowDown: [0, -10] }[event.key];
    if (!step) return;
    event.preventDefault();
    view.x += step[0];
    view.y += step[1];
    draw();
  });

  dialog.querySelectorAll("[data-dialog-close]").forEach(function (button) { button.addEventListener("click", close); });
  dialog.addEventListener("cancel", function (event) { event.preventDefault(); close(); });
  dialog.addEventListener("click", function (event) { if (event.target === dialog) close(); });

  // show the new picture here and in the top right corner, without a new page
  function showEverywhere(url) {
    var preview = document.querySelector("[data-avatar-preview]");
    if (preview) preview.innerHTML = '<img alt="" src="' + url + '">';
    var corner = document.querySelector("#topbar-user .topbar-avatar");
    if (corner) {
      var image = document.createElement("img");
      image.className = "topbar-avatar is-picture";
      image.alt = "";
      image.width = image.height = 34;
      image.src = url;
      corner.replaceWith(image);
    }
    spots(url);
    var remove = document.querySelector("[data-avatar-remove]");
    if (remove) remove.hidden = false;
    var label = choose.querySelector("span");
    if (label) label.textContent = "Change picture";
  }

  // Remove: the letter again, here and in the corner
  var remove = document.querySelector("[data-avatar-remove]");
  if (remove) {
    remove.addEventListener("submit", function (event) {
      event.preventDefault();   // in the background: no new page, so nothing moves (page-swap.js)
      fetch(remove.action, { method: "POST", body: new FormData(remove), credentials: "same-origin",
                             headers: { Accept: "application/json" } })
        .then(function (response) {
          remove.dispatchEvent(new Event("someless:done"));   // its button stops spinning (busy-button.js)
          if (!response.ok) throw new Error("refused");
          var preview = document.querySelector("[data-avatar-preview]");
          if (preview) preview.textContent = preview.dataset.letter;
          var corner = document.querySelector("#topbar-user .topbar-avatar");
          if (corner) {
            var letter = document.createElement("span");
            letter.className = "topbar-avatar";
            letter.setAttribute("aria-hidden", "true");
            letter.textContent = preview ? preview.dataset.letter : "";
            corner.replaceWith(letter);
          }
          spots(null);
          remove.hidden = true;
          var label = choose.querySelector("span");
          if (label) label.textContent = "Upload picture";
          board("success", "Removed", "Your profile picture is gone: your initial shows instead.");
        })
        .catch(function () {
          remove.dispatchEvent(new Event("someless:done"));
          board("error", "Couldn't remove the picture", NO_ANSWER);
        });
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();   // sent here, with the file (page-swap.js stays out of it)
    if (!chosen) return;
    // where the square around the circle is, in the picture's own pixels
    form.elements.x.value = Math.round(-view.x / view.scale);
    form.elements.y.value = Math.round(-view.y / view.scale);
    form.elements.size.value = Math.round(side() / view.scale);
    var data = new FormData(form);
    data.append("picture", chosen);
    fetch(form.action, { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json().then(function (answer) { return { ok: response.ok, data: answer }; }, function () {
          return { ok: false, data: { problem: response.status === 413 ? "Choose a picture of 5 MB or less." : "Try again." } };
        });
      })
      .then(function (answer) {
        form.dispatchEvent(new Event("someless:done"));
        if (!answer.ok) return board("error", "Couldn't save the picture", answer.data.problem || "Try again.");
        showEverywhere(answer.data.url);
        close();
        setTimeout(function () { board("success", "Saved", "Your profile picture is in place."); }, 200);
      })
      .catch(function () {
        form.dispatchEvent(new Event("someless:done"));
        board("error", "Couldn't save the picture", NO_ANSWER);
      });
  });
})();
