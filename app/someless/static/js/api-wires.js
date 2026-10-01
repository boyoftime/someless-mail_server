// The API guide (api-docs.html): down the right of its cards, five glowing ropes, waving and weaving
// round each other as a gentle current flows down them, with a branch into each card that ends in
// a softly pulsing knot on its edge. Bright sparks run down the ropes, and out along a branch as
// they pass it, lighting its knot. Drawn on one canvas fixed over the window, only where the ropes
// are on the screen; it rests while the tab is hidden and goes with the page (page-swap.js).
// Too narrow a window: none (the cards need the room). Less motion asked for: they hang still.
(function () {
  var docs = document.querySelector("[data-api-wires]");
  var canvas = docs && docs.querySelector(".api-wires");
  if (!canvas || !canvas.getContext) return;
  var context = canvas.getContext("2d");
  var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var wide = window.matchMedia("(min-width: 1100px)");
  var GAP = 40;   // px from the cards' right edge to the ropes
  // each rope: its colour (bright in both themes), how far it waves, where in the wave it starts, how fast
  var ROPES = [
    { colour: "1, 149, 251", wave: 11, phase: 0, pace: 1 },
    { colour: "56, 189, 248", wave: 9, phase: 1.3, pace: 1.12 },
    { colour: "124, 131, 255", wave: 13, phase: 2.5, pace: 0.9 },
    { colour: "167, 139, 250", wave: 8, phase: 3.8, pace: 1.2 },
    { colour: "34, 211, 238", wave: 10, phase: 5, pace: 1.05 },
  ];
  // How each rope is drawn, in passes, wide and faint to thin and bright: [width, colour, opacity].
  // Dark: light added to light, glowing. Light (on the island's warm earth): a soft shadow first to
  // lift it off the ground, a stronger glow, and a white shine down its middle, so it shines.
  var PASSES = {
    dark: [[14, null, 0.06], [5, null, 0.18], [1.8, null, 0.9]],
    light: [[7, "40, 25, 70", 0.2], [16, null, 0.16], [6, null, 0.42], [2.2, null, 1], [0.9, "255, 255, 255", 0.85]],
  };
  var cards = [], spine = 0, first = 0, last = 0, width = 0, height = 0, ratio = 1;
  var time = 0, before = 0, frame = 0, measured = 0;
  var sparks = [], outward = [];

  // Where the cards are. Again every second and after the page's flip in (page-flip.js): the page
  // comes in turning over, so where they seemed to be as it started isn't where they settle.
  function measure() {
    var scrolled = window.scrollY;
    var was = cards;
    cards = Array.from(docs.querySelectorAll(".api-land > .page-header, .api-land > .smtp-card, .api-index, .api-call")).map(function (card, index) {
      var box = card.getBoundingClientRect();
      // its knot: level with the card's title (page coordinates: the window's scrolling is taken off as it draws)
      return { edge: box.right, y: box.top + scrolled + Math.min(54, box.height / 2), glow: was[index] ? was[index].glow : 0 };
    });
    spine = cards.length ? Math.max.apply(null, cards.map(function (card) { return card.edge; })) + GAP : 0;
    first = cards.length ? cards[0].y : 0;
    last = cards.length ? cards[cards.length - 1].y : 0;
    var size = [canvas.clientWidth, canvas.clientHeight, Math.min(window.devicePixelRatio || 1, 2)];
    if (size[0] !== width || size[1] !== height || size[2] !== ratio) {
      width = size[0];
      height = size[1];
      ratio = size[2];
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    if (!sparks.length) {
      for (var i = 0; i < 5; i += 1) sparks.push({ rope: i, y: first + Math.random() * (last - first), speed: 120 + Math.random() * 110 });
    }
  }

  function ropeX(rope, y) {   // the spine: each rope waving round the middle, its waves flowing down
    return spine + rope.wave * Math.sin(y * 0.015 - time * 1.8 * rope.pace + rope.phase)
      + 3.5 * Math.sin(y * 0.005 - time * 0.6 + rope.phase * 1.7);
  }

  function branchPoint(card, index, rope, s, top) {   // s: 0 at the card's edge, 1 at the spine
    var x = card.edge + (ropeX(rope, card.y) - card.edge) * s;
    var y = card.y + (index - 2) * 3.2 * s + rope.wave * 0.45 * Math.sin(s * Math.PI * 2 - time * 3 * rope.pace + rope.phase) * Math.sin(s * Math.PI);
    return { x: x, y: y - top };
  }

  function draw() {
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    if (!wide.matches || cards.length < 2) return;
    var top = window.scrollY;
    var dark = document.documentElement.dataset.theme === "dark";
    var from = Math.max(first, top - 40), to = Math.min(last, top + height + 40);
    context.globalCompositeOperation = dark ? "lighter" : "source-over";
    context.lineCap = "round";
    context.lineJoin = "round";
    var seen = cards.filter(function (card) { return card.y > top - 60 && card.y < top + height + 60; });
    ROPES.forEach(function (rope, index) {
      var path = new Path2D();
      if (to > from) {
        for (var y = from; y <= to; y += 5) {
          var x = ropeX(rope, y);
          if (y === from) path.moveTo(x, y - top);
          else path.lineTo(x, y - top);
        }
      }
      seen.forEach(function (card) {
        for (var step = 0; step <= 10; step += 1) {
          var point = branchPoint(card, index, rope, step / 10, top);
          if (step === 0) path.moveTo(point.x, point.y);
          else path.lineTo(point.x, point.y);
        }
      });
      PASSES[dark ? "dark" : "light"].forEach(function (pass) {
        context.lineWidth = pass[0];
        context.strokeStyle = "rgba(" + (pass[1] || rope.colour) + ", " + pass[2] + ")";
        context.stroke(path);
      });
    });
    seen.forEach(function (card) {   // the knots, glowing brighter as a spark arrives
      var glow = card.glow;
      var x = card.edge, y = card.y - top;
      var halo = context.createRadialGradient(x, y, 0, x, y, 12 + glow * 8);
      var strength = (dark ? 0.55 : 0.75) + glow * 0.25;
      halo.addColorStop(0, "rgba(" + (dark ? "127, 211, 255" : "56, 189, 248") + ", " + strength + ")");
      halo.addColorStop(1, "rgba(1, 149, 251, 0)");
      context.fillStyle = halo;
      context.beginPath();
      context.arc(x, y, 12 + glow * 8, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = dark ? "#e6f6ff" : "#ffffff";   // (a bright white centre in both themes)
      context.beginPath();
      context.arc(x, y, 2.6 + glow * 1.4, 0, Math.PI * 2);
      context.fill();
      if (!dark) {
        context.lineWidth = 1.4;
        context.strokeStyle = "rgba(1, 149, 251, 0.9)";
        context.stroke();
      }
    });
    sparks.forEach(function (spark) { light(ropeX(ROPES[spark.rope], spark.y), spark.y - top, dark); });
    outward.forEach(function (spark) {
      if (!cards[spark.card]) return;
      var point = branchPoint(cards[spark.card], spark.rope, ROPES[spark.rope], spark.s, top);
      light(point.x, point.y, dark);
    });
    context.globalCompositeOperation = "source-over";
  }

  function light(x, y, dark) {   // a spark: a bright core in a soft glow
    if (y < -20 || y > height + 20) return;
    var glow = context.createRadialGradient(x, y, 0, x, y, dark ? 9 : 11);
    glow.addColorStop(0, "rgba(255, 255, 255, 0.95)");
    glow.addColorStop(0.35, dark ? "rgba(127, 211, 255, 0.55)" : "rgba(56, 189, 248, 0.7)");
    glow.addColorStop(1, "rgba(1, 149, 251, 0)");
    context.fillStyle = glow;
    context.beginPath();
    context.arc(x, y, dark ? 9 : 11, 0, Math.PI * 2);
    context.fill();
  }

  function move(seconds) {
    sparks.forEach(function (spark) {
      var was = spark.y;
      spark.y += spark.speed * seconds;
      cards.forEach(function (card, index) {   // passing a branch: a spark runs out along it to the card
        if (was < card.y && spark.y >= card.y) outward.push({ card: index, rope: spark.rope, s: 1 });
      });
      if (spark.y > last) {
        spark.y = first - Math.random() * 300;
        spark.speed = 120 + Math.random() * 110;
      }
    });
    outward = outward.filter(function (spark) {
      spark.s -= seconds * 2.6;
      if (spark.s <= 0 && cards[spark.card]) cards[spark.card].glow = 1;
      return spark.s > 0;
    });
    cards.forEach(function (card) { card.glow = Math.max(0, card.glow - seconds * 1.4); });
  }

  function tick(now) {
    if (!canvas.isConnected) return stop();   // left the page
    var seconds = before ? Math.min((now - before) / 1000, 1 / 20) : 0;
    before = now;
    if (now - measured > 1000) {
      measured = now;
      measure();
    }
    time += seconds;
    move(seconds);
    draw();
    frame = requestAnimationFrame(tick);
  }

  function settled() {   // the page's flip in is over
    measure();
    if (still) draw();
  }

  function stop() {
    cancelAnimationFrame(frame);
    window.removeEventListener("resize", measure);
    if (main) main.removeEventListener("animationend", settled);
    window.removeEventListener("scroll", drawStill);
    document.removeEventListener("someless:theme", drawStill);
    if (watching) watching.disconnect();
  }

  function drawStill() {
    if (!canvas.isConnected) return stop();
    draw();
  }

  var watching = window.ResizeObserver ? new ResizeObserver(function () { measure(); if (still) draw(); }) : null;
  if (watching) watching.observe(docs);
  window.addEventListener("resize", measure);
  var main = document.getElementById("app-main");
  if (main) main.addEventListener("animationend", settled);
  measure();
  if (still) {
    window.addEventListener("scroll", drawStill, { passive: true });
    document.addEventListener("someless:theme", drawStill);
    draw();
  } else {
    frame = requestAnimationFrame(tick);
  }
})();
