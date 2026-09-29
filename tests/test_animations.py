"""The Lottie animations (static/lottie) are played by lottie_light.min.js, which runs no
expressions: motion an animation leaves to one (loopOut() and the like) simply doesn't happen.
So none may rely on one, and the webmail's loading arrows turn in the frames they play."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOTTIE = ROOT / "app" / "someless" / "static" / "lottie"


def expressions(node, where=""):
    """Where an animation leaves a value to an expression (a property's "x", written as code)."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "x" and isinstance(value, str):
                found.append(where)
            found += expressions(value, f"{where}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += expressions(value, f"{where}[{index}]")
    return found


def test_no_animation_relies_on_an_expression():
    animations = sorted(LOTTIE.glob("*.json"))
    assert animations
    relying = {path.name: expressions(json.loads(path.read_text(encoding="utf-8"))) for path in animations}
    assert {name: where for name, where in relying.items() if where} == {}


def test_the_webmail_loading_arrows_turn_in_the_frames_played():
    animation = json.loads((LOTTIE / "webmail-loading.json").read_text(encoding="utf-8"))
    turn = animation["layers"][0]["ks"]["r"]
    assert turn["a"] == 1   # (keyframed)
    keys = turn["k"]
    first, last = animation["ip"], animation["op"]
    before = [key for key in keys if key["t"] <= first]
    after = [key for key in keys if key["t"] >= last]
    # a keyframe at or before the first frame played and one at or after the last, with the arrows
    # turned further at the end: turning all the way through
    assert before and after
    assert after[0]["s"][0] > before[-1]["s"][0]
