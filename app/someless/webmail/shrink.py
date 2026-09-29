"""Files attached in the webmail (compose.py), made smaller without losing anything, before they go
into the mailbox: less of its storage, and faster mail.

- A PNG is packed again (Pillow, optimize): the same pixels, its colour profile kept. One that
  Pillow can't carry exactly (16 bits a channel, animated, its own gamma) is left as it is.
- A JPEG goes through jpegtran (-optimize -progressive -copy all): only the way its picture is
  written down changes, not a pixel of it, and everything in it is kept (the phone's rotation too).
- A PDF goes through qpdf: its streams packed again, and its objects in streams of their own.
  Nothing in it changes; a signed one (its signature covers its bytes), a PDF/A (whose rules
  forbid object streams) and a locked one are left as they are.

The result is taken only when it's smaller; anything going wrong, the file is used as it came.
jpegtran and qpdf are in the Docker image; without them (a developer's computer), JPEGs and PDFs
go as they are."""
import io
import logging
import os
import shutil
import struct
import subprocess
import tempfile

from PIL import Image

TIMEOUT = 90   # seconds, for the biggest PDF allowed
UNSAFE_PNG_CHUNKS = {b"gAMA", b"cHRM", b"acTL"}   # its own gamma or colours, or animated: kept as it is

log = logging.getLogger(__name__)


def shrink(data, kind):
    """The file's bytes, smaller if they can be made so without losing anything."""
    try:
        if kind == "image/png":
            smaller = _png(data)
        elif kind == "image/jpeg":
            smaller = _jpeg(data)
        elif kind == "application/pdf":
            smaller = _pdf(data)
        else:
            return data
    except Exception:   # a file that can't be read the way its type says: it goes as it came
        log.warning("couldn't make a %s smaller", kind, exc_info=True)
        return data
    return smaller if smaller and len(smaller) < len(data) else data


def _png_chunks(data):
    """(bit depth, the kinds of chunk before the picture)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None, set()
    found, position, depth = set(), 8, None
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        if kind == b"IHDR":
            depth = data[position + 16]
        if kind == b"IDAT":
            break
        found.add(kind)
        position += 12 + length
    return depth, found


def _png(data):
    depth, chunks = _png_chunks(data)
    if depth != 8 and depth not in (1, 2, 4) or chunks & UNSAFE_PNG_CHUNKS:
        return None
    with Image.open(io.BytesIO(data)) as picture:
        if picture.format != "PNG" or getattr(picture, "is_animated", False):
            return None
        picture.load()
        options = {"optimize": True}
        for key in ("icc_profile", "transparency", "dpi"):
            if picture.info.get(key) is not None:
                options[key] = picture.info[key]
        out = io.BytesIO()
        picture.save(out, "PNG", **options)
    return out.getvalue()


def _jpeg(data):
    tool = shutil.which("jpegtran")
    if not tool or data[:2] != b"\xff\xd8":
        return None
    done = subprocess.run([tool, "-copy", "all", "-optimize", "-progressive"], input=data, capture_output=True,
                          timeout=TIMEOUT, check=False)
    return done.stdout if done.returncode == 0 and done.stdout[:2] == b"\xff\xd8" else None


def _pdf(data):
    tool = shutil.which("qpdf")
    if not tool or not data.startswith(b"%PDF") or any(mark in data for mark in (b"/ByteRange", b"pdfaid:part", b"/Encrypt")):
        return None
    with tempfile.TemporaryDirectory() as folder:
        source, target = os.path.join(folder, "in.pdf"), os.path.join(folder, "out.pdf")
        with open(source, "wb") as file:
            file.write(data)
        done = subprocess.run([tool, "--object-streams=generate", "--compress-streams=y", "--recompress-flate",
                               "--compression-level=9", source, target], capture_output=True, timeout=TIMEOUT, check=False)
        if done.returncode not in (0, 3) or not os.path.exists(target):   # (3: warnings, a file mended on the way)
            return None
        with open(target, "rb") as file:
            return file.read()
