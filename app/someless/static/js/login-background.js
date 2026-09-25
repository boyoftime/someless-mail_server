// Login page background, drawn with PixiJS (WebGL): mail icons (static/img/float/, listed in
// FLOAT_ICONS in someless/__init__.py) float behind the login card, each repeated many times.
// When the page opens they rain in from the top and settle, spread out so each one can
// be seen. Then each floats freely in its own direction, turning slowly. Every icon has a
// little personal space: icons that come close gently push each other away and curve past
// smoothly, and the screen edges and the login card push them away softly too. That keeps
// them spread evenly over the screen instead of bunching up in one area.
// When the login card flips, a short gust of wind blows outwards from it.
// Without WebGL or JavaScript the page simply has a plain background.
(async function () {
  var holder = document.querySelector(".login-bg");
  var PIXI = window.PIXI;
  if (!holder || !PIXI || !holder.dataset.icons) return;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var app = new PIXI.Application();
  try {
    await app.init({
      resizeTo: window,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
    });
  } catch (error) {
    return;
  }
  holder.appendChild(app.canvas);

  var iconUrls = holder.dataset.icons.trim().split(/\s+/);
  var loaded = await PIXI.Assets.load(iconUrls);
  var textures = iconUrls.map(function (url) { return loaded[url]; });

  var far = new PIXI.Container();
  var near = new PIXI.Container();
  far.filters = [new PIXI.BlurFilter({ strength: 1 })];
  var streaks = new PIXI.Container();
  app.stage.addChild(far, near, streaks);

  var ICON_SIZE = 110; // pixels at scale 1, on a large screen
  var SPACE = 70; // extra personal space around each icon, in pixels: wide enough that
                  // crowded areas push icons into emptier ones, so they spread out evenly
  var EDGE = 48; // how far from the screen edges and the login card the soft push starts
  var icons = [];

  function screenSize() {
    return { w: app.screen.width, h: app.screen.height };
  }
  function random(min, max) {
    return min + Math.random() * (max - min);
  }

  // About 18 icons on a phone, up to 60 on a big screen. Phones get smaller ones.
  function wantedIcons() {
    var s = screenSize();
    return Math.max(18, Math.min(60, Math.round((s.w * s.h) / 26000)));
  }
  function sizeFactor() {
    return screenSize().w < 640 ? 0.7 : 1;
  }
  function wideScreen() {
    return screenSize().w >= 900;
  }

  // The login card, as an area the icons are gently pushed away from.
  function loginCardArea() {
    var el = document.querySelector(".flip-card");
    if (!el || !wideScreen()) return null;
    var r = el.getBoundingClientRect();
    return { left: r.left - 6, right: r.right + 6, top: r.top - 6, bottom: r.bottom + 6 };
  }

  // Mostly the left and right sides on wide screens; anywhere on phones.
  function randomX() {
    var s = screenSize();
    if (!wideScreen() || Math.random() < 0.1) return random(0, s.w);
    var clear = Math.min(320, s.w * 0.22);
    var side = (s.w / 2 - clear) * random(0, 1);
    return Math.random() < 0.5 ? side : s.w - side;
  }

  // Of a few random spots, pick the one furthest from the other icons.
  function spreadOutSpot(icon, pickY) {
    var best = null;
    var bestRoom = -Infinity;
    for (var i = 0; i < 12; i++) {
      var spot = { x: randomX(), y: pickY() };
      var room = Infinity;
      icons.forEach(function (other) {
        if (other === icon || other.x === undefined) return;
        var d = Math.hypot(other.x - spot.x, other.y - spot.y) - other.radius - icon.radius;
        room = Math.min(room, d);
      });
      if (room > bestRoom) {
        bestRoom = room;
        best = spot;
      }
    }
    return best;
  }

  // Depth 0 = far (small, slow, dimmer, blurred), 1 = near (big, faster, brighter).
  // Raising the random number to a power makes small far icons the most common.
  function giveLook(icon) {
    var depth = Math.pow(Math.random(), 1.8);
    icon.depth = depth;
    icon.sprite.texture = textures[Math.floor(Math.random() * textures.length)];
    icon.size = ICON_SIZE * (0.25 + depth * 0.9) * sizeFactor();
    icon.radius = icon.size * 0.5; // icons touch when their circles touch
    icon.mass = icon.size * icon.size; // bigger icons push smaller ones harder
    // float in any direction, faster when near; after pushes they ease back to this speed
    var heading = random(0, Math.PI * 2);
    icon.cruise = random(6, 14) + depth * 22;
    icon.vx = Math.cos(heading) * icon.cruise;
    icon.vy = Math.sin(heading) * icon.cruise;
    icon.wobbleAmp = random(0.05, 0.14);
    icon.wobbleFreq = random(0.2, 0.45);
    icon.turn = random(-0.35, 0.35);
    icon.turnSpeed = random(-0.12, 0.12); // slow spin, radians per second
    icon.phase = random(0, Math.PI * 2);
    icon.sprite.width = icon.size;
    icon.sprite.height = icon.size;
    icon.sprite.alpha = 0.35 + depth * 0.35;
    (depth < 0.25 ? far : near).addChild(icon.sprite);
  }

  // First visit: every icon starts above the screen and falls into a spread-out spot.
  function rainIn(icon) {
    var s = screenSize();
    giveLook(icon);
    var spot = spreadOutSpot(icon, function () { return random(0.04, 0.96) * s.h; });
    icon.x = spot.x;
    icon.y = spot.y;
    icon.intro = {
      fromY: -icon.size - random(0, s.h * 0.35),
      toY: spot.y,
      delay: random(0, 1.1),
      duration: random(1.4, 2.4),
      time: 0,
    };
  }

  // No motion wanted: lay the icons out, spread over the screen, and keep them still.
  function layOut(icon) {
    giveLook(icon);
    var spot = spreadOutSpot(icon, function () { return random(0.04, 0.96) * screenSize().h; });
    icon.x = spot.x;
    icon.y = spot.y;
    icon.intro = null;
  }

  function newIcon(entrance) {
    var icon = { sprite: new PIXI.Sprite(textures[0]), spin: 0, spinV: 0 };
    icon.sprite.anchor.set(0.5);
    icons.push(icon);
    entrance(icon);
  }

  var count = wantedIcons();
  for (var n = 0; n < count; n++) newIcon(reduceMotion ? layOut : rainIn);

  // When the window changes size (e.g. DevTools opening and closing), move every icon to
  // the same relative spot on the new screen, and rain any extra icons in quickly, so the
  // screen stays evenly filled.
  var lastSize = screenSize();
  var resizeTimer = null;
  function refit() {
    var s = screenSize();
    var sx = s.w / lastSize.w;
    var sy = s.h / lastSize.h;
    lastSize = s;
    icons.forEach(function (icon) {
      icon.x *= sx;
      icon.y *= sy;
      if (icon.intro) icon.intro.toY *= sy;
    });
    while (icons.length < wantedIcons()) newIcon(reduceMotion ? layOut : rainIn);
    while (icons.length > wantedIcons()) icons.pop().sprite.destroy();
  }
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(refit, 150);
  });

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  // Soft push that grows smoothly from 0 (at the edge of the range) to 1 (right up close).
  function softness(distance, range) {
    var t = 1 - distance / range;
    return t > 0 ? t * t : 0;
  }

  // Gentle forces that keep the icons spread out: icons push each other away when they come
  // close (the lighter one gives way more), and the screen edges and the login card push
  // them back softly. Everything changes speed gradually, so paths curve smoothly.
  function keepApart(dt) {
    for (var i = 0; i < icons.length; i++) {
      var a = icons[i];
      if (a.intro) continue;
      for (var j = i + 1; j < icons.length; j++) {
        var b = icons[j];
        if (b.intro) continue;
        var dx = b.x - a.x;
        var dy = b.y - a.y;
        var range = a.radius + b.radius + SPACE;
        var d2 = dx * dx + dy * dy;
        if (d2 >= range * range) continue;
        var d = Math.sqrt(d2) || 0.01;
        var nx = dx / d;
        var ny = dy / d;
        var push = 180 * softness(d, range) * dt;
        var total = a.mass + b.mass;
        var giveA = (2 * b.mass) / total;
        var giveB = (2 * a.mass) / total;
        a.vx -= nx * push * giveA;
        a.vy -= ny * push * giveA;
        b.vx += nx * push * giveB;
        b.vy += ny * push * giveB;
        // never let them sit on top of each other
        var overlap = a.radius + b.radius - d;
        if (overlap > 0) {
          a.x -= nx * overlap * 0.1 * giveA;
          a.y -= ny * overlap * 0.1 * giveA;
          b.x += nx * overlap * 0.1 * giveB;
          b.y += ny * overlap * 0.1 * giveB;
        }
      }
    }

    var s = screenSize();
    var area = loginCardArea();
    icons.forEach(function (icon) {
      if (icon.intro) return;
      var r = icon.radius;
      var edge = r + EDGE;
      // screen edges
      icon.vx += 200 * softness(icon.x, edge) * dt;
      icon.vx -= 200 * softness(s.w - icon.x, edge) * dt;
      icon.vy += 200 * softness(icon.y, edge) * dt;
      icon.vy -= 200 * softness(s.h - icon.y, edge) * dt;
      // login card
      if (!area) return;
      var cx = Math.max(area.left, Math.min(icon.x, area.right));
      var cy = Math.max(area.top, Math.min(icon.y, area.bottom));
      var dx = icon.x - cx;
      var dy = icon.y - cy;
      var d = Math.hypot(dx, dy);
      if (d === 0) {
        // right on top of the card: slide out of the nearer side
        icon.vx += (icon.x < (area.left + area.right) / 2 ? -1 : 1) * 300 * dt;
        return;
      }
      var cardPush = 260 * softness(d, edge) * dt;
      icon.vx += (dx / d) * cardPush;
      icon.vy += (dy / d) * cardPush;
    });
  }

  function moveIcon(icon, dt) {
    var s = screenSize();
    if (icon.intro) {
      var intro = icon.intro;
      intro.time += dt;
      var t = Math.max(0, intro.time - intro.delay) / intro.duration;
      icon.y = intro.fromY + (intro.toY - intro.fromY) * easeOutCubic(Math.min(t, 1));
      if (t >= 1) icon.intro = null;
      return;
    }
    // ease back towards cruising speed after pushes and gusts
    var speed = Math.hypot(icon.vx, icon.vy);
    if (speed < 0.5) {
      var heading = random(0, Math.PI * 2);
      icon.vx = Math.cos(heading);
      icon.vy = Math.sin(heading);
      speed = 1;
    }
    var adjust = 1 + (icon.cruise / speed - 1) * Math.min(1, 1.2 * dt);
    icon.vx *= adjust;
    icon.vy *= adjust;
    icon.x += icon.vx * dt;
    icon.y += icon.vy * dt;
    icon.turn += icon.turnSpeed * dt;
    // never leave the screen (the soft push above normally stops them well before this);
    // an icon that reaches an edge turns back instead of sliding along it
    var r = icon.radius;
    if (icon.x < r) { icon.x = r; icon.vx = Math.abs(icon.vx) * 0.5; }
    else if (icon.x > s.w - r) { icon.x = s.w - r; icon.vx = -Math.abs(icon.vx) * 0.5; }
    if (icon.y < r) { icon.y = r; icon.vy = Math.abs(icon.vy) * 0.5; }
    else if (icon.y > s.h - r) { icon.y = s.h - r; icon.vy = -Math.abs(icon.vy) * 0.5; }
  }

  // Gust of wind: blows outwards from the login card, pushing every icon away from it and
  // turning it a little. They glide back to cruising speed within a second or two.
  var activeStreaks = [];
  function gust() {
    if (reduceMotion) return;
    var card = document.querySelector(".flip-card");
    var box = card ? card.getBoundingClientRect() : null;
    var cx = box ? (box.left + box.right) / 2 : screenSize().w / 2;
    var cy = box ? (box.top + box.bottom) / 2 : screenSize().h / 2;
    icons.forEach(function (icon) {
      var dx = icon.x - cx;
      var dy = icon.y - cy;
      var d = Math.hypot(dx, dy) || 1;
      var push = random(140, 240) * (0.4 + icon.depth);
      icon.vx += (dx / d) * push;
      icon.vy += (dy / d) * push;
      icon.spinV += random(-1.2, 1.2);
    });
    var s = screenSize();
    for (var i = 0; i < Math.round(s.h / 22); i++) {
      var streak = new PIXI.Sprite(PIXI.Texture.WHITE);
      streak.tint = document.documentElement.dataset.theme === "light" ? 0x1463f3 : 0xffffff;
      streak.width = random(80, 220);
      streak.height = random(1, 2.5);
      streak.x = -streak.width - random(0, s.w * 0.5);
      streak.y = random(0, s.h);
      streak.alpha = 0;
      streaks.addChild(streak);
      activeStreaks.push({ sprite: streak, speed: random(1400, 2400), peak: random(0.12, 0.35), life: 0, span: random(0.7, 1.1) });
    }
  }
  document.addEventListener("someless:wind", gust);

  var time = 0;
  app.ticker.add(function (ticker) {
    var dt = Math.min(ticker.deltaMS / 1000, 0.05);
    var s = screenSize();
    if (!reduceMotion) time += dt;

    if (!reduceMotion) keepApart(dt);
    icons.forEach(function (icon) {
      if (!reduceMotion) {
        moveIcon(icon, dt);
        // turning from gusts settles back smoothly
        icon.spinV += (-5 * icon.spin - 2.8 * icon.spinV) * dt;
        icon.spin += icon.spinV * dt;
      }
      icon.sprite.x = icon.x;
      icon.sprite.y = icon.y;
      icon.sprite.rotation = icon.turn + icon.wobbleAmp * Math.sin(time * icon.wobbleFreq * 2 * Math.PI + icon.phase * 1.7) + icon.spin;
    });

    for (var i = activeStreaks.length - 1; i >= 0; i--) {
      var st = activeStreaks[i];
      st.life += dt;
      st.sprite.x += st.speed * dt;
      var t = st.life / st.span;
      st.sprite.alpha = st.peak * Math.sin(Math.min(t, 1) * Math.PI);
      if (t >= 1 || st.sprite.x > s.w) {
        st.sprite.destroy();
        activeStreaks.splice(i, 1);
      }
    }
  });
})();
