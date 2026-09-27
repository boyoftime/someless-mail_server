"""The admin's profile picture (Settings > Account): uploaded, cut to the square the admin placed
over it (settings-avatar.js), made 512 by 512 and saved as WebP, which keeps it sharp and small,
and shown in the top right corner. It's kept in the data folder, as avatar.webp."""
import io
import os
import tempfile
from pathlib import Path

from flask import current_app, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

LARGEST = 5 * 1024 * 1024        # bytes, as uploaded
MOST_PIXELS = 40_000_000         # a picture that opens up bigger is refused (a "decompression bomb")
SIDE = 512                       # pixels, the saved picture's width and height
KINDS = {"JPEG", "PNG", "WEBP", "GIF"}
NOT_A_PICTURE = "That file isn't a picture Someless Mail can read. Choose a JPEG, PNG, WebP or GIF picture."


def path():
    # the whole path: a relative data folder (./devdata) would be looked for inside the app's
    # own folder when the file is sent
    return Path(current_app.config["DATA_DIR"]).resolve() / "avatar.webp"


def url():
    """Where the picture is served, changing whenever it does (so browsers can keep it); None
    without one."""
    picture = path()
    return url_for("settings.avatar_image", v=int(picture.stat().st_mtime_ns // 1000)) if picture.exists() else None


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def save(data, x, y, size):
    """Cut the square at (x, y), size pixels wide, out of the uploaded picture (kept inside it),
    and keep it as the profile picture. None when that went well, else what went wrong."""
    if len(data) > LARGEST:
        return "Choose a picture of 5 MB or less."
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in KINDS:
                return NOT_A_PICTURE
            if picture.width * picture.height > MOST_PIXELS:
                return "That picture is too big to open. Choose a smaller one."
            picture.load()   # reading it all: a damaged file fails here
            picture = ImageOps.exif_transpose(picture)   # a phone photo, the right way up
            picture = picture.convert("RGBA" if "A" in picture.getbands() or picture.mode == "P" else "RGB")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return NOT_A_PICTURE
    width, height = picture.size
    side = min(max(_number(size, min(width, height)), 1), width, height)
    left = min(max(_number(x, 0), 0), width - side)
    top = min(max(_number(y, 0), 0), height - side)
    square = picture.crop((round(left), round(top), round(left + side), round(top + side)))
    square = square.resize((SIDE, SIDE), Image.Resampling.LANCZOS)
    # written next to the old one, then swapped in: never half a picture
    folder = path().parent
    handle, temporary = tempfile.mkstemp(dir=folder, suffix=".webp")
    try:
        with os.fdopen(handle, "wb") as out:
            square.save(out, "WEBP", quality=90, method=6)
        os.replace(temporary, path())
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return None


def remove():
    path().unlink(missing_ok=True)
