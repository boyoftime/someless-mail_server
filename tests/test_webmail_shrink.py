"""Files attached in the webmail made smaller without losing anything (webmail/shrink.py): PNGs
packed again with the same pixels, JPEGs through jpegtran, PDFs through qpdf; anything that could
change (16-bit or animated PNGs, signed or PDF/A or locked PDFs) left as it came."""
import io
import subprocess

from PIL import Image

from someless.webmail import shrink


def a_png(mode="RGB", size=(120, 80), **options):
    picture = Image.new(mode, size)
    for x in range(size[0]):
        for y in range(size[1]):
            picture.putpixel((x, y), (x * 2 % 256, y * 3 % 256, (x + y) % 256) if mode == "RGB" else (x + y) % 256)
    out = io.BytesIO()
    picture.save(out, "PNG", compress_level=0, **options)   # (packed as loosely as can be)
    return out.getvalue()


def pixels(data):
    with Image.open(io.BytesIO(data)) as picture:
        return picture.mode, picture.size, picture.tobytes()


def test_a_png_is_packed_again_with_the_same_pixels():
    loose = a_png()

    tight = shrink.shrink(loose, "image/png")

    assert len(tight) < len(loose)
    assert pixels(tight) == pixels(loose)


def test_a_pngs_colour_profile_is_kept():
    profile = b"\x00" * 128
    loose = a_png(icc_profile=profile)

    tight = shrink.shrink(loose, "image/png")

    with Image.open(io.BytesIO(tight)) as picture:
        assert picture.info.get("icc_profile") == profile


def test_a_16_bit_png_is_left_as_it_is():
    picture = Image.new("I;16", (40, 40), 40000)
    out = io.BytesIO()
    picture.save(out, "PNG", compress_level=0)
    wide = out.getvalue()

    assert shrink.shrink(wide, "image/png") is wide


def test_a_png_with_its_own_gamma_is_left_as_it_is():
    loose = a_png()
    gamma = b"\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfc\x61\x05"
    with_gamma = loose[:33] + gamma + loose[33:]   # (after IHDR)

    assert shrink.shrink(with_gamma, "image/png") is with_gamma


def test_a_file_that_isnt_what_it_says_goes_as_it_came():
    assert shrink.shrink(b"not a picture", "image/png") == b"not a picture"


def test_other_kinds_go_as_they_came():
    data = b"GIF89a..."

    assert shrink.shrink(data, "image/gif") is data


def test_nothing_bigger_is_taken(monkeypatch):
    monkeypatch.setattr(shrink, "_png", lambda data: data + b"more")

    assert shrink.shrink(b"\x89PNG", "image/png") == b"\x89PNG"


# --- JPEG and PDF: through the tools in the image ---

class Ran:
    def __init__(self, output=b"", code=0):
        self.calls = []
        self.output, self.code = output, code

    def __call__(self, command, **options):
        self.calls.append((command, options))
        if "--compression-level=9" in command:   # qpdf writes to its last argument
            with open(command[-1], "wb") as file:
                file.write(self.output)
        return subprocess.CompletedProcess(command, self.code, stdout=self.output if "-optimize" in command else b"", stderr=b"")


def test_a_jpeg_goes_through_jpegtran_keeping_everything(monkeypatch):
    ran = Ran(output=b"\xff\xd8smaller")
    monkeypatch.setattr(shrink.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(shrink.subprocess, "run", ran)

    assert shrink.shrink(b"\xff\xd8" + b"x" * 100, "image/jpeg") == b"\xff\xd8smaller"
    command, options = ran.calls[0]
    assert command == ["/usr/bin/jpegtran", "-copy", "all", "-optimize", "-progressive"]
    assert options["input"].startswith(b"\xff\xd8")


def test_without_jpegtran_a_jpeg_goes_as_it_came(monkeypatch):
    monkeypatch.setattr(shrink.shutil, "which", lambda name: None)
    photo = b"\xff\xd8" + b"x" * 100

    assert shrink.shrink(photo, "image/jpeg") is photo


def test_a_pdf_goes_through_qpdf(monkeypatch):
    ran = Ran(output=b"%PDF-1.7 small")
    monkeypatch.setattr(shrink.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(shrink.subprocess, "run", ran)

    assert shrink.shrink(b"%PDF-1.4 " + b"x" * 200, "application/pdf") == b"%PDF-1.7 small"
    command = ran.calls[0][0]
    assert command[:5] == ["/usr/bin/qpdf", "--object-streams=generate", "--compress-streams=y", "--recompress-flate",
                           "--compression-level=9"]


def test_signed_pdfa_and_locked_pdfs_are_left_as_they_are(monkeypatch):
    ran = Ran(output=b"%PDF-1.7 small")
    monkeypatch.setattr(shrink.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(shrink.subprocess, "run", ran)

    for mark in (b"/ByteRange [0 10 20 30]", b"<pdfaid:part>1</pdfaid:part>", b"/Encrypt 5 0 R"):
        document = b"%PDF-1.4 " + mark + b"x" * 200
        assert shrink.shrink(document, "application/pdf") is document
    assert ran.calls == []


def test_a_pdf_qpdf_cant_read_goes_as_it_came(monkeypatch):
    monkeypatch.setattr(shrink.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(shrink.subprocess, "run", Ran(output=b"", code=2))
    document = b"%PDF-1.4 " + b"x" * 200

    assert shrink.shrink(document, "application/pdf") is document
