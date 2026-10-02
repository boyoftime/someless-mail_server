"""The relay's front page (supervisor.py): what opening http://mail.example.com/ shows, once the
proxy host passes it on to Someless Mail. "It's all done!" in blocks of grass, the API guide's and
the Dashboard's tiles (Kenney, CC0), dropping into place, over a sky with Someless Mail as a
watermark. Anyone on the internet can open it, so it's one self-contained page: its pictures are in
it, it runs no script, and the relay sends it with a policy that lets it load nothing else."""
import base64
import functools
from pathlib import Path

TILES = Path(__file__).resolve().parent.parent / "static" / "img" / "api"
WORDS = ["IT'S", "ALL", "DONE!"]
# The letters, five blocks high: # a block, . none
GLYPHS = {
    "I": ["###", ".#.", ".#.", ".#.", "###"],
    "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "'": ["#", "#", ".", ".", "."],
    "S": ["###", "#..", "###", "..#", "###"],
    "A": ["###", "#.#", "###", "#.#", "#.#"],
    "L": ["#..", "#..", "#..", "#..", "###"],
    "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "O": ["###", "#.#", "#.#", "#.#", "###"],
    "N": ["#..#", "##.#", "#.##", "#..#", "#..#"],
    "E": ["###", "#..", "###", "#..", "###"],
    "!": ["#", "#", "#", ".", "#"],
}


def blocks(letter):
    """The letter's blocks, row by row: top (grass on it: nothing above), bottom (a rough edge:
    nothing under it), fill (earth), or None (no block)."""
    rows = GLYPHS[letter]

    def there(row, column):
        return 0 <= row < len(rows) and rows[row][column] == "#"

    return [[None if not there(row, column) else "top" if not there(row - 1, column)
             else "bottom" if not there(row + 1, column) else "fill"
             for column in range(len(rows[row]))] for row in range(len(rows))]


def _tile(name):
    return "url(data:image/png;base64," + base64.b64encode((TILES / f"grass-{name}.png").read_bytes()).decode() + ")"


def _words():
    number = 0
    words = []
    for word in WORDS:
        letters = []
        for letter in word:
            cells = "".join(f'<i class="{kind}"></i>' if kind else "<i></i>" for row in blocks(letter) for kind in row)
            letters.append(f'<span class="letter w{len(GLYPHS[letter][0])}" style="--n:{number}">{cells}</span>')
            number += 1
        words.append(f'<span class="word">{"".join(letters)}</span>')
    return "".join(words)


STYLE = """
:root {
  color-scheme: light dark;
  --sky-top: #6fc3f7; --sky-low: #e3f5ff;
  --ink: #0f1a3d; --muted: #3d4a70;
  --card: rgba(255, 255, 255, 0.86); --card-line: rgba(15, 26, 61, 0.1);
  --mark: rgba(15, 26, 61, 0.07); --star: transparent;
  --b: clamp(11px, 1.6vw + 6px, 32px);
}
@media (prefers-color-scheme: dark) {
  :root {
    --sky-top: #030820; --sky-low: #183374;
    --ink: #eef3ff; --muted: #b8c5ea;
    --card: rgba(8, 16, 44, 0.8); --card-line: rgba(160, 190, 255, 0.18);
    --mark: rgba(255, 255, 255, 0.05); --star: rgba(255, 255, 255, 0.75);
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-rows: 1fr auto;
  overflow-x: hidden;
  background: linear-gradient(180deg, var(--sky-top), var(--sky-low));
  color: var(--ink);
  font: 400 1rem/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.sky {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  overflow: hidden;
  pointer-events: none;
  background-image: radial-gradient(1.5px 1.5px at 12% 18%, var(--star), transparent),
    radial-gradient(1px 1px at 38% 9%, var(--star), transparent),
    radial-gradient(1.5px 1.5px at 66% 24%, var(--star), transparent),
    radial-gradient(1px 1px at 84% 12%, var(--star), transparent),
    radial-gradient(1px 1px at 52% 40%, var(--star), transparent);
  background-size: 420px 300px;
}
.watermark {
  transform: rotate(-12deg);
  color: var(--mark);
  font-size: clamp(3.5rem, 15vw, 13rem);
  font-weight: 800;
  letter-spacing: -0.04em;
  white-space: nowrap;
}
@media (max-aspect-ratio: 4/5) {   /* a phone: on two lines, in the open sky above the ground */
  .sky { place-items: end center; padding-bottom: calc(var(--b) * 3 + 5vh); }
  .watermark { width: min-content; font-size: 17vw; line-height: 0.95; text-align: center; white-space: normal; transform: rotate(-8deg); }
}
main {
  position: relative;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: clamp(1.75rem, 5vw, 2.75rem);
  padding: clamp(2.5rem, 8vh, 5rem) 16px clamp(1.5rem, 4vh, 2.5rem);
  text-align: center;
}
h1 { margin: 0; }
.words { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--b) calc(var(--b) * 1.6); }
.word { display: flex; gap: calc(var(--b) * 0.55); }
.letter {
  display: grid;
  grid-auto-rows: var(--b);
  filter: drop-shadow(0 calc(var(--b) * 0.35) calc(var(--b) * 0.3) rgba(4, 12, 40, 0.28));
  animation: drop 0.75s cubic-bezier(0.3, 1.35, 0.55, 1) both;
  animation-delay: calc(var(--n) * 70ms + 150ms);
}
.w1 { grid-template-columns: var(--b); }
.w3 { grid-template-columns: repeat(3, var(--b)); }
.w4 { grid-template-columns: repeat(4, var(--b)); }
.letter i { display: block; background-size: 100% 100%; }
@keyframes drop { from { transform: translateY(-110vh); } }
.card {
  max-width: 34rem;
  padding: 1.1rem 1.4rem 1.2rem;
  border: 1px solid var(--card-line);
  border-radius: 18px;
  background: var(--card);
  box-shadow: 0 18px 40px -22px rgba(4, 10, 40, 0.55);
  animation: rise 0.6s ease-out 1.25s both;
}
@keyframes rise { from { opacity: 0; transform: translateY(12px); } }
.card p { margin: 0; color: var(--muted); text-wrap: pretty; }
.card strong { color: var(--ink); }
.card .small { margin-top: 0.45rem; font-size: 0.88rem; }
.ground {
  position: relative;
  height: calc(var(--b) * 3);
  background-image: TOP, FILL;
  background-position: 0 0, 0 var(--b);
  background-size: var(--b) var(--b);
  background-repeat: repeat-x, repeat;
}
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@media (prefers-reduced-motion: reduce) {
  .letter, .card { animation: none; }
}
"""


@functools.cache
def page():
    """The page, as bytes (made once)."""
    tiles = {name: _tile(name) for name in ("top", "fill", "bottom")}
    style = STYLE.replace("TOP", tiles["top"]).replace("FILL", tiles["fill"])
    style += "".join(f".{name} {{ background-image: {url}; }}\n" for name, url in tiles.items())
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>It's all done | Someless Mail</title>
<style>{style}</style>
</head>
<body>
<div class="sky" aria-hidden="true"><div class="watermark" aria-hidden="true">Someless Mail</div></div>
<main>
<h1><span class="visually-hidden">It's all done!</span><span class="words" aria-hidden="true">{_words()}</span></h1>
<div class="card">
<p><strong>Your proxy host works.</strong> Let's Encrypt's checks get through to Someless Mail here, so your mail server's certificate comes by itself: follow it on <strong>SMTP &amp; API</strong> in your Someless Mail panel.</p>
<p class="small">Nothing else is served on this address.</p>
</div>
</main>
<div class="ground" aria-hidden="true"></div>
</body>
</html>
""".encode()
