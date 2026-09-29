// The rocket that takes a message off (webmail-compose.js). Send, and it rises out of the button
// on a blue flame, smoke gathering under it, while the message goes; the moment the webmail says
// it's sent, it gathers itself and blasts off up the screen. Still waiting, it hovers, rumbling;
// not sent, it sputters out. (static/lottie/webmail-rocket.json: LottieFiles' rocket, in the
// webmail's blues, with a flame of ours.) It's on the page's top layer, over everything, and the
// pointer goes through it. With less motion asked for, there's none.
//   var flight = wm.rocket(button); flight.sent(); flight.failed()
(function () {
  if (!window.wm) return;
  var source = document.querySelector('meta[name="wm-rocket"]');
  var SIZE = 280;       // px: its box, the bottom of which is the button's middle
  var WAIT_AT = 42;     // the frame it hovers at until it's sent; after it, the dip and lift-off
  var HURRY = 1.9;      // its speed once it's sent while it's still rising: on to lift-off
  var LIFT_OFF = 53;    // the frame it leaves the ground: a flash of light where it stood
  var asked = null;

  function load() {
    if (!asked && source && window.fetch) {
      asked = fetch(source.content).then(function (response) { return response.json(); })
        .then(function (data) { return data; }, function () { return null; });
    }
    return asked || Promise.resolve(null);
  }

  wm.rocket = function (button) {
    var none = { sent: function () {}, failed: function () {} };
    var rect = button && button.getBoundingClientRect();
    if (wm.reduceMotion || !window.lottie || !rect || !rect.width) return none;
    var box = document.createElement("div");
    box.className = "wm-rocket";
    box.setAttribute("aria-hidden", "true");
    box.style.left = Math.round(rect.left + rect.width / 2 - SIZE / 2) + "px";
    box.style.top = Math.round(rect.top + rect.height / 2 - SIZE) + "px";
    document.body.appendChild(box);
    if (typeof box.showPopover === "function") {   // (over an open dialog, and the whole screen too)
      box.setAttribute("popover", "manual");
      box.showPopover();
    }
    var sent = false;
    var gone = false;
    var player = null;

    function finish() {
      gone = true;
      if (player) player.destroy();
      box.remove();
    }
    function onward() {   // sent: on to lift-off, quicker while it's still rising
      if (!player) return;
      box.classList.remove("is-holding");
      if (player.currentFrame < WAIT_AT) player.setSpeed(HURRY);
      if (player.isPaused) player.play();
    }
    load().then(function (data) {
      if (gone) return;
      if (!data) {
        finish();
        return;
      }
      player = window.lottie.loadAnimation({ container: box, renderer: "svg", loop: false, autoplay: true,
                                             animationData: JSON.parse(JSON.stringify(data)) });
      player.addEventListener("enterFrame", function () {
        if (player.currentFrame < WAIT_AT) return;
        if (!sent && !player.isPaused) {   // not yet: it hovers, rumbling
          player.pause();
          box.classList.add("is-holding");
        } else if (sent && player.playSpeed !== 1) {
          player.setSpeed(1);   // the dip and lift-off, as they are
        }
        if (sent && player.currentFrame >= LIFT_OFF) box.classList.add("is-lifting");
      });
      player.addEventListener("complete", finish);
      if (sent) onward();
    });
    return {
      sent: function () {
        sent = true;
        onward();
      },
      failed: function () {
        if (gone) return;
        gone = true;
        box.classList.add("is-sputtering");
        setTimeout(function () {
          if (player) player.destroy();
          box.remove();
        }, 450);
      },
    };
  };

  // ready before the first Send (it's small)
  setTimeout(load, 2500);
})();
