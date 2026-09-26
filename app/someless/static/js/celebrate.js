// A celebration over the whole screen: the domain's records are all right, just now
// (domain.html marks it with data-celebrate, the one time). A glow flashes from the middle with
// a ring of light running out, confetti, little gift boxes, stars and sparkles burst out from
// it (twice, like fireworks) and from the two bottom corners, then float down and fade.
// Drawn on a canvas above the page that lets clicks through, under the "Authenticated" board,
// and gone after a few seconds. Not with reduced motion.
(function () {
  var marker = document.querySelector("[data-celebrate]");
  if (!marker) return;
  marker.remove(); // once, even if this script runs again
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var COLORS = ["#0195fb", "#4db3ff", "#22c55e", "#facc15", "#a855f7", "#f472b6", "#ffffff"];
  var LIFE = 5600; // ms, the last 1.2 s fading
  var GRAVITY = 620; // px per second, every second
  var FALL = { confetti: 140, star: 175, gift: 230, sparkle: 95 }; // how fast each can fall, px/s: they float

  var canvas = document.createElement("canvas");
  canvas.className = "celebrate";
  canvas.setAttribute("aria-hidden", "true");
  document.body.appendChild(canvas);
  var ctx = canvas.getContext("2d");
  var ratio = Math.min(window.devicePixelRatio || 1, 2);
  var width = 0;
  var height = 0;
  function size() {
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }
  size();
  window.addEventListener("resize", size);

  function between(a, b) { return a + Math.random() * (b - a); }
  function pick(list) { return list[Math.floor(Math.random() * list.length)]; }

  var particles = [];
  function burst(x, y, count, angle, spread, speed, delay) {
    for (var i = 0; i < count; i += 1) {
      var direction = angle + between(-spread, spread);
      var velocity = between(speed * 0.4, speed);
      var roll = Math.random();
      particles.push({
        kind: roll < 0.6 ? "confetti" : roll < 0.78 ? "star" : roll < 0.9 ? "gift" : "sparkle",
        x: x, y: y,
        vx: Math.cos(direction) * velocity, vy: Math.sin(direction) * velocity,
        size: between(9, 16), color: pick(COLORS), ribbon: pick(COLORS),
        turn: between(0, Math.PI * 2), spin: between(-7, 7),
        flip: between(5, 11), phase: between(0, Math.PI * 2),
        born: delay + between(0, 140),
      });
    }
  }
  var reach = Math.max(width, height);
  var middle = { x: width / 2, y: height * 0.45 };
  burst(middle.x, middle.y, 150, 0, Math.PI, reach * 0.7, 80);             // the explosion, every way
  burst(0, height, 90, -Math.PI / 3, 0.3, reach * 0.95, 0);                // bottom left, up and in
  burst(width, height, 90, -Math.PI * 2 / 3, 0.3, reach * 0.95, 0);        // bottom right
  burst(middle.x, middle.y - height * 0.08, 90, 0, Math.PI, reach * 0.5, 750); // and a second, like fireworks

  function star(radius) {
    ctx.beginPath();
    for (var i = 0; i < 10; i += 1) {
      var r = i % 2 ? radius * 0.45 : radius;
      var a = -Math.PI / 2 + (i * Math.PI) / 5;
      ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
    }
    ctx.closePath();
    ctx.fill();
  }

  function gift(p) {
    var s = p.size * 1.7;
    ctx.fillStyle = p.color;
    ctx.fillRect(-s / 2, -s / 2, s, s);
    ctx.fillStyle = p.ribbon === p.color ? "#ffffff" : p.ribbon;
    ctx.fillRect(-s * 0.1, -s / 2, s * 0.2, s); // the ribbon, down
    ctx.fillRect(-s / 2, -s * 0.1, s, s * 0.2); // and across
    ctx.beginPath(); // the bow
    ctx.ellipse(-s * 0.16, -s / 2 - s * 0.1, s * 0.16, s * 0.1, -0.5, 0, Math.PI * 2);
    ctx.ellipse(s * 0.16, -s / 2 - s * 0.1, s * 0.16, s * 0.1, 0.5, 0, Math.PI * 2);
    ctx.fill();
  }

  function draw(p, t) {
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.turn);
    ctx.fillStyle = p.color;
    if (p.kind === "confetti") {
      ctx.scale(1, Math.cos(p.phase + (t / 1000) * p.flip)); // a strip of paper turning over
      ctx.fillRect(-p.size / 2, -p.size * 0.22, p.size, p.size * 0.44);
    } else if (p.kind === "star") {
      ctx.shadowColor = p.color;
      ctx.shadowBlur = 18;
      ctx.globalAlpha *= 0.7 + 0.3 * Math.sin(p.phase + t / 90); // twinkling
      star(p.size);
    } else if (p.kind === "gift") {
      gift(p);
    } else {
      ctx.shadowColor = "#bfe6ff";
      ctx.shadowBlur = 16;
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(0, 0, p.size * 0.28, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function glow(t) {
    // the flash from the middle, growing and fading
    var k = t / 1200;
    var radius = reach * (0.15 + 0.6 * k);
    var light = ctx.createRadialGradient(middle.x, middle.y, 0, middle.x, middle.y, radius);
    light.addColorStop(0, "rgba(186, 230, 253, " + 0.6 * (1 - k) + ")");
    light.addColorStop(0.4, "rgba(1, 149, 251, " + 0.3 * (1 - k) + ")");
    light.addColorStop(1, "rgba(1, 149, 251, 0)");
    ctx.fillStyle = light;
    ctx.fillRect(0, 0, width, height);
  }

  function ring(t, delay, color) {
    // a ring of light running out from the middle
    var k = (t - delay) / 900;
    if (k < 0 || k > 1) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.globalAlpha = 1 - k;
    ctx.lineWidth = 6 * (1 - k) + 1;
    ctx.shadowColor = color;
    ctx.shadowBlur = 24;
    ctx.beginPath();
    ctx.arc(middle.x, middle.y, reach * 0.45 * (1 - Math.pow(1 - k, 3)), 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  var start = performance.now();
  var last = start;
  function frame(now) {
    var t = now - start;
    var dt = Math.min(now - last, 50) / 1000;
    last = now;
    ctx.clearRect(0, 0, width, height);
    if (t < 1200) glow(t);
    ring(t, 0, "#7dd3fc");
    ring(t, 180, "#facc15");
    ctx.globalAlpha = t > LIFE - 1200 ? Math.max(0, (LIFE - t) / 1200) : 1;
    var drag = Math.pow(0.28, dt);
    particles.forEach(function (p) {
      if (t < p.born) return;
      p.vx *= drag;
      p.vy = Math.min(p.vy * drag + GRAVITY * dt, FALL[p.kind]);
      p.x += p.vx * dt + Math.sin(p.phase + t / 400) * 0.4; // a little sway on the way down
      p.y += p.vy * dt;
      p.turn += p.spin * dt;
      draw(p, t);
    });
    ctx.globalAlpha = 1;
    if (t < LIFE) {
      window.requestAnimationFrame(frame);
    } else {
      window.removeEventListener("resize", size);
      canvas.remove();
    }
  }
  window.requestAnimationFrame(frame);
})();
