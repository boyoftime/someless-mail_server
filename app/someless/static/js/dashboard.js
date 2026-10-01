// The Dashboard's boards (dashboard.html): the domains, the mailboxes, the senders and the mail
// server, and under them the server itself (its RAM, disk and health, refreshed), each hanging
// from two ropes. As the page opens they drop in one after another and bounce on their ropes, then
// hang nearly still, barely stirring. Every 15 seconds a helicopter flies across over them, and its
// downwash swings each board as it passes, each in its own way. A board under the pointer calms
// down, to be clicked. PixiJS draws the ropes, following each board as it moves, and the breeze drifting
// by; the boards are the page's own links, moved each frame. Leaving the page (page-swap.js) stops
// it all. With less motion asked for, or without PixiJS (or WebGL), they hang still, their ropes
// drawn in CSS.
(function () {
  var hang = document.querySelector("[data-dash-hang]");
  if (!hang || hang.dataset.started) return;
  hang.dataset.started = "1";
  var sky = hang.querySelector("[data-dash-sky]");
  var holder = hang.querySelector(".dash-boards");
  var boards = Array.prototype.slice.call(hang.querySelectorAll("[data-dash-board]"));
  if (!sky || !boards.length) return;

  // A beam over each row of boards, a little wider than the row (one row on a wide screen; on a
  // narrow one, a board a row): what their ropes are tied to
  var beams = [];
  function size(name, fallback) { return parseFloat(getComputedStyle(hang).getPropertyValue(name)) || fallback; }
  function putBeams() {
    var rope = size("--rope", 76), beam = size("--beam", 26);
    var rows = {};
    boards.forEach(function (el) {
      var top = holder.offsetTop + el.offsetTop;
      (rows[top] = rows[top] || []).push(el);
    });
    beams.forEach(function (one) { one.remove(); });
    beams = Object.keys(rows).map(function (top) {
      var left = Math.min.apply(null, rows[top].map(function (el) { return holder.offsetLeft + el.offsetLeft; })) - 18;
      var right = Math.max.apply(null, rows[top].map(function (el) { return holder.offsetLeft + el.offsetLeft + el.offsetWidth; })) + 18;
      var one = document.createElement("div");
      one.className = "dash-beam";
      one.setAttribute("aria-hidden", "true");
      one.style.left = left + "px";
      one.style.width = (right - left) + "px";
      one.style.top = (Number(top) - rope - beam) + "px";
      hang.appendChild(one);
      return one;
    });
  }
  putBeams();
  if (window.ResizeObserver) new ResizeObserver(putBeams).observe(holder);

  // The server's boards (the cake ones) ask for their figures again every so often, while the page
  // is open and in sight: the words change in place, the meters slide, the boards keep swaying
  var stats = hang.dataset.stats;
  var refreshing = stats && setInterval(function () {
    if (!hang.isConnected) return clearInterval(refreshing);   // left the page
    if (document.hidden) return;
    fetch(stats, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (found) { if (found) show(found); })
      .catch(function () { /* the next round tries again */ });
  }, 15000);
  function show(found) {
    Object.keys(found).forEach(function (key) {
      var board = hang.querySelector("[data-stat='" + key + "']");
      if (!board) return;
      var card = found[key], health = key === "health";
      var count = board.querySelector("[data-stat-count]");
      count.textContent = health ? card.title : card.count;
      count.classList.toggle("is-word", health || card.count === "Can't tell here");   // (words, not a figure: smaller)
      board.querySelector("[data-stat-label]").textContent = health ? card.detail : card.label;
      if (health) board.dataset.state = card.state;
      var meter = board.querySelector("[data-stat-meter]");
      if (meter && typeof card.used === "number") {
        meter.style.setProperty("--used", card.used.toFixed(1) + "%");
        meter.classList.toggle("is-high", card.used >= 85);
      }
    });
  }
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;   // (hanging still)
  hang.classList.add("is-arming");   // (out of sight till each drops in)

  var GRAVITY = 1700;   // px/s²: how fast a board swings back (its rhythm: about a second and a half)
  var DAMPING = 0.75;   // how fast a swing dies down
  var CALM = 6;         // and under the pointer
  var STAGGER = 0.2;    // s between one board dropping in and the next
  var RING = 0.3;       // the rings: this far either side of a board's middle, as its width

  function still() {   // (no PixiJS: they hang as they are)
    hang.classList.remove("is-arming");
  }

  function pixi() {
    if (window.PIXI) return Promise.resolve(window.PIXI);
    return new Promise(function (resolve) {
      var script = document.createElement("script");
      script.src = hang.dataset.pixi;
      script.onload = function () { resolve(window.PIXI || null); };
      script.onerror = function () { resolve(null); };
      document.head.appendChild(script);
    });
  }

  var waited = setTimeout(still, 4000);   // (PixiJS slow to come: they hang still meanwhile)
  pixi().then(function (PIXI) {
    clearTimeout(waited);
    if (!PIXI || !hang.isConnected) return still();
    var app = new PIXI.Application();
    return app.init({ resizeTo: sky, backgroundAlpha: 0, antialias: true, autoDensity: true,
                      resolution: Math.min(window.devicePixelRatio || 1, 2) })
      .then(function () { start(PIXI, app); }, still);
  });

  function start(PIXI, app) {
    if (!hang.isConnected) {
      app.destroy(true);
      return;
    }
    sky.appendChild(app.canvas);
    hang.classList.remove("is-arming");
    hang.classList.add("is-live");
    var breeze = new PIXI.Graphics();
    var ropes = new PIXI.Graphics();
    app.stage.addChild(breeze, ropes);

    var rope = size("--rope", 76), beam = size("--beam", 26);
    var hung = boards.map(function (el, index) {
      var one = { el: el, angle: 0, spin: 0, drop: 0, fall: 0, wait: index * STAGGER, calm: false,
                  phase: [Math.random() * 6.3, Math.random() * 6.3, Math.random() * 6.3], pace: 0.85 + Math.random() * 0.3 };
      el.addEventListener("pointerenter", function () { one.calm = true; });
      el.addEventListener("pointerleave", function () { one.calm = false; });
      return one;
    });
    var firstRowY = 0;   // (where the top row hangs: the helicopter flies over its ropes)
    function measure() {   // where each hangs at rest (as the page lays it out)
      var firstRow = Infinity;
      hung.forEach(function (one) {
        one.x = holder.offsetLeft + one.el.offsetLeft;
        one.y = holder.offsetTop + one.el.offsetTop;
        one.w = one.el.offsetWidth;
        one.h = one.el.offsetHeight;
        one.length = rope + one.h / 2;   // (a pendulum from the hooks to its middle)
        firstRow = Math.min(firstRow, one.y);
      });
      firstRowY = firstRow;
      hung.forEach(function (one) {
        if (one.started) return;
        // Waiting to drop in. The top row: up out of sight, from under the first beam. A row below
        // (a narrow window, the boards one under another): just under its own beam, unseen, to fade
        // in as it comes down onto its ropes, never across the boards above it.
        one.fade = one.y > firstRow + 1;
        one.drop = one.from = one.fade ? -(rope + one.h * 0.6) : -(one.y + one.h + 30);
        one.el.style.transform = "translateY(" + one.drop + "px)";
        one.el.style.opacity = one.fade ? "0" : "";
      });
    }
    measure();

    // The air: so calm the boards barely stir. Every 15 seconds a helicopter flies across, from left to
    // right, nose down a little and bobbing, just over the boards' ropes; its downwash reaches each
    // board as it passes over it, pushing it away from the rotor, fluttering it, then lets it swing
    // back on its own, the nearest ones most
    var HELI_EVERY = 15;     // s between flights (the first 15 s after the page opens)
    var HELI_CROSSING = 8;   // s to fly across
    var DOWNWASH = 7;        // how hard it pushes a board right under it
    var heliEl = hang.querySelector(".dash-heli");
    var heli = { flying: false, next: HELI_EVERY, start: 0, cx: -9999, cy: 0 };
    var streaks = [];
    for (var count = 0; count < 14; count++) {
      streaks.push({ x: Math.random(), y: Math.random(), length: 30 + Math.random() * 90, speed: 30 + Math.random() * 50,
                     alpha: 0.03 + Math.random() * 0.07, thick: Math.random() < 0.3 ? 2 : 1 });
    }
    function wind(one, time) {
      var t = time * one.pace;
      var play = Math.sin(t * 0.9 + one.phase[0]) + 0.55 * Math.sin(t * 2.1 + one.phase[1]) + 0.3 * Math.sin(t * 3.7 + one.phase[2]);
      return play * 0.15 + downwash(one, time);   // (rad/s², roughly)
    }
    function downwash(one, time) {
      if (!heli.flying) return 0;
      var dx = one.x + one.w / 2 - heli.cx;                     // (+: the board is ahead of it)
      var dy = Math.max(0, one.y + one.h / 2 - heli.cy);        // (the rows further down feel it less)
      var reach = Math.max(one.w * 0.75, 140);
      var near = Math.exp(-(dx * dx) / (2 * reach * reach)) / (1 + dy / 260);
      var away = Math.tanh(dx / 70);                             // blown away from the rotor, either side
      var flutter = 0.55 * Math.sin(time * 9 * one.pace + one.phase[1] * 3);   // (each in its own way)
      return DOWNWASH * near * (away + flutter);
    }
    function fly(time) {   // the helicopter: setting off every 15 seconds, across, then gone
      if (!heliEl) return;
      if (!heli.flying && time >= heli.next) {
        heli.flying = true;
        heli.start = time;
        heliEl.classList.add("is-flying");
      }
      if (!heli.flying) return;
      var progress = (time - heli.start) / HELI_CROSSING;
      if (progress >= 1) {
        heli.flying = false;
        heli.next = time + HELI_EVERY;
        heli.cx = -9999;
        heliEl.classList.remove("is-flying");
        heliEl.style.transform = "";   // (back at the start, out of sight)
        return;
      }
      // across its lane, from past the menu's edge to past the window's (the lane reaches past the
      // boards' space on both sides: its left is where 0 is, in the lane's own terms)
      var lane = heliEl.parentElement, w = heliEl.offsetWidth, h = heliEl.offsetHeight;
      heli.cx = lane.offsetLeft - w + (lane.offsetWidth + 2 * w) * progress;   // (in the boards' terms, for the downwash)
      heli.cy = firstRowY - rope * 0.55 + Math.sin(time * 2.6) * 5;   // (over the first row's ropes, bobbing)
      var tilt = 7 + Math.sin(time * 1.7) * 2;                         // (nose down, as it flies forward)
      heliEl.style.transform = "translate(" + (heli.cx - lane.offsetLeft - w / 2).toFixed(1) + "px, " + (heli.cy - h / 2).toFixed(1)
        + "px) rotate(" + tilt.toFixed(2) + "deg) scaleX(-1)";   // (it's drawn facing left: turned to face where it flies)
    }

    var time = 0;
    var dark = document.documentElement.dataset.theme === "dark";
    function themed() { dark = document.documentElement.dataset.theme === "dark"; }
    document.addEventListener("someless:theme", themed);
    var watching = window.ResizeObserver ? new ResizeObserver(measure) : null;
    if (watching) watching.observe(holder);

    app.ticker.add(function (ticker) {
      if (!hang.isConnected) {   // left the page: all of it goes
        if (watching) watching.disconnect();
        document.removeEventListener("someless:theme", themed);
        app.destroy(true, { children: true });
        return;
      }
      var dt = Math.min(ticker.deltaMS / 1000, 1 / 30);
      time += dt;
      var width = sky.clientWidth, height = sky.clientHeight;
      fly(time);
      breeze.clear();
      streaks.forEach(function (streak) {   // the air drifting by, faint; stirred up round the helicopter
        var x = streak.x * width, y = streak.y * height;
        var stirred = heli.flying ? Math.exp(-Math.pow((x - heli.cx) / 220, 2)) : 0;
        streak.x += streak.speed * (1 + stirred * 6) * dt / Math.max(1, width);
        if (streak.x > 1.15) streak.x = -0.15;
        breeze.moveTo(x, y).lineTo(x + streak.length, y + streak.length * 0.04)
          .stroke({ width: streak.thick, color: dark ? 0xbfe0ff : 0x1d46c9, alpha: streak.alpha * (dark ? 1 : 0.55) * (1 + stirred * 3) });
      });

      ropes.clear();
      function bolt(x, y) {   // (in the beam's middle, over the rope's end)
        ropes.circle(x, y, 5).fill({ color: 0x5b6478 });
        ropes.circle(x, y, 2).fill({ color: 0xdfe4f2 });
      }
      hung.forEach(function (one) {
        if (time < one.wait) {   // (its bolts in the beam already, its ropes still to come)
          [-1, 1].forEach(function (side) { bolt(one.x + one.w / 2 + side * one.w * RING, one.y - rope - beam / 2); });
          return;
        }
        one.started = true;
        // dropping in: a spring pulling it down to where it hangs, overshooting a little (the ropes take it)
        one.fall += (-170 * one.drop - 13 * one.fall) * dt;
        one.drop += one.fall * dt;
        if (one.fade) {   // (a row below: seen more as it comes down, wholly by the time it hangs)
          var seen = 1 - Math.max(0, Math.min(1, one.drop / one.from));
          one.el.style.opacity = seen >= 0.999 ? "" : seen.toFixed(3);
          if (seen >= 0.999) one.fade = false;
        }
        // swaying: a pendulum from the hooks, pushed by the wind, the swing dying down
        var push = wind(one, time) * (Math.abs(one.drop) < 40 ? 1 : 0.2);
        one.spin += (-(GRAVITY / one.length) * Math.sin(one.angle) - (one.calm ? CALM : DAMPING) * one.spin + push * 0.55) * dt;
        one.angle += one.spin * dt;
        var shift = one.length * Math.sin(one.angle);
        var lift = one.length * (1 - Math.cos(one.angle));
        var tilt = one.angle * 0.4;
        one.el.style.transform = "translate(" + shift.toFixed(2) + "px, " + (one.drop + lift).toFixed(2) + "px) rotate(" + tilt.toFixed(4) + "rad)";
        // its ropes: from a bolt in the beam's middle to the rings, taut, over the beam
        var middleX = one.x + one.w / 2, topY = one.y;
        [-1, 1].forEach(function (side) {
          var hookX = middleX + side * one.w * RING, hookY = topY - rope - beam / 2;
          var ringX = middleX + shift + side * one.w * RING * Math.cos(tilt);
          var ringY = topY + one.drop + lift + side * one.w * RING * Math.sin(tilt);
          if (ringY > hookY + 2) {
            ropes.moveTo(hookX, hookY).lineTo(ringX, ringY).stroke({ width: 4, color: 0x9c7a4c, cap: "round" });
            ropes.moveTo(hookX, hookY).lineTo(ringX, ringY).stroke({ width: 2, color: 0xd8b98a, alpha: 0.9, cap: "round" });
          }
          bolt(hookX, hookY);
        });
      });
    });
  }
})();
