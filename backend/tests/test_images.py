import io

import pytest
from PIL import Image

from app.config import get_settings
from app.images import (
    MAX_UPLOAD_BYTES,
    ImageRejected,
    decrypt,
    encrypt,
    fingerprint,
    normalize_document_number,
    prepare_image,
)
from tests.conftest import png_bytes


def test_output_is_jpeg_without_metadata():
    src = png_bytes(fmt="JPEG", exif={34853: {1: "N"}, 271: "Camera"})
    assert len(Image.open(io.BytesIO(src)).getexif()) > 0
    out = prepare_image(src)
    assert out.startswith(b"\xff\xd8")
    assert len(Image.open(io.BytesIO(out)).getexif()) == 0


def test_downscales_longest_side():
    out = prepare_image(png_bytes(size=(4000, 3000)))
    assert Image.open(io.BytesIO(out)).size == (1600, 1200)


def test_portrait_orientation_is_applied():
    out = prepare_image(png_bytes(size=(300, 200), fmt="JPEG", exif={274: 6}))
    assert Image.open(io.BytesIO(out)).size == (200, 300)


def _huge_png() -> bytes:
    buf = io.BytesIO()
    Image.new("1", (7000, 6000)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize(
    "data,message",
    [
        (b"not an image", "Use a JPEG, PNG or WebP image"),
        (png_bytes(fmt="GIF"), "Use a JPEG, PNG or WebP image"),
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100, "Use a JPEG, PNG or WebP image"),
        (b"\x00" * (MAX_UPLOAD_BYTES + 1), None),
        (_huge_png(), None),
    ],
    ids=["junk", "gif", "heic", "too-big", "too-many-pixels"],
)
def test_rejects(data, message):
    with pytest.raises(ImageRejected) as exc:
        prepare_image(data)
    if message:
        assert str(exc.value) == message


def test_encrypt_roundtrip():
    token = encrypt(b"x" * 100)
    assert b"x" * 100 not in token
    assert decrypt(token) == b"x" * 100


def test_fingerprint_folds_lookalikes():
    assert fingerprint("АВ 123-456") == fingerprint("ab123456")
    assert fingerprint("ab123456") != fingerprint("AB123457")
    assert len(fingerprint("ab123456")) == 64


def test_normalize():
    assert normalize_document_number(" a.b-1 2 ") == "AB12"


def test_config_requires_verification_key(monkeypatch):
    monkeypatch.setenv("VERIFICATION_KEY", "short-key")
    with pytest.raises(RuntimeError):
        get_settings()
