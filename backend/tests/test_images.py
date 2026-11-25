import io

import pytest
from PIL import Image, ImageCms

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


def test_comment_icc_and_xmp_are_stripped():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(
        buf, format="JPEG", comment=b"SECRET-COMMENT",
        icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes(),
        xmp=b"<x:xmpmeta>SECRET-XMP</x:xmpmeta>",
    )
    src = buf.getvalue()
    assert b"SECRET-COMMENT" in src and b"SECRET-XMP" in src
    out = prepare_image(src)
    info = Image.open(io.BytesIO(out)).info
    for key in ("comment", "icc_profile", "xmp"):
        assert key not in info
    assert b"SECRET-COMMENT" not in out and b"SECRET-XMP" not in out


def test_multi_picture_jpeg_is_accepted():
    buf = io.BytesIO()
    a, b = Image.new("RGB", (64, 64), "red"), Image.new("RGB", (64, 64), "blue")
    a.save(buf, format="MPO", save_all=True, append_images=[b])
    assert Image.open(io.BytesIO(buf.getvalue())).format == "MPO"
    assert prepare_image(buf.getvalue()).startswith(b"\xff\xd8")


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_pixel_check_does_not_rely_on_warnings(monkeypatch):
    # 42 MP is above the limit; ignore the bomb warning so only the explicit check can reject it.
    import warnings

    monkeypatch.setattr(warnings, "simplefilter", lambda *a, **k: None)
    with pytest.raises(ImageRejected) as exc:
        prepare_image(_huge_png())
    assert str(exc.value) == "Image is too large (40 megapixels maximum)"


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
