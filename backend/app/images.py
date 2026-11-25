"""Cleaning, encryption and fingerprinting for identity-verification images."""
import base64
import hashlib
import hmac
import io
import warnings

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from PIL import Image, ImageOps

from app.config import settings

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SIDE = 1600
MAX_PIXELS = 40_000_000
_FORMATS = {"JPEG", "PNG", "WEBP"}
_UNSUPPORTED = "Use a JPEG, PNG or WebP image"

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageRejected(ValueError):
    """The message is safe to show to the user."""


def _derive(info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=info
    ).derive(settings.verification_key.encode())


_fernet = Fernet(base64.urlsafe_b64encode(_derive(b"razom image encryption")))
_hmac_key = _derive(b"razom document fingerprint")


def prepare_image(data: bytes) -> bytes:
    """Validate an upload and return a clean JPEG: oriented, downscaled, no metadata."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected("Image is too large (5 MB maximum)")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in _FORMATS:
                raise ImageRejected(_UNSUPPORTED)
            img.load()
    except ImageRejected:
        raise
    except Image.DecompressionBombError:
        raise ImageRejected("Image is too large (40 megapixels maximum)") from None
    except Image.DecompressionBombWarning:
        raise ImageRejected("Image is too large (40 megapixels maximum)") from None
    except Exception:
        raise ImageRejected(_UNSUPPORTED) from None
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)  # no exif=, so no metadata is written
    return out.getvalue()


def encrypt(data: bytes) -> bytes:
    return _fernet.encrypt(data)


def decrypt(token: bytes) -> bytes:
    return _fernet.decrypt(token)


# Cyrillic letters that look like Latin ones, folded so a document typed on another keyboard matches.
_FOLD = str.maketrans("АВЕІКМНОРСТУХ", "ABEIKMHOPCTYX")


def normalize_document_number(raw: str) -> str:
    s = raw.upper()
    s = "".join(c for c in s if c not in " -.")
    return s.translate(_FOLD)


def fingerprint(document_number: str) -> str:
    return hmac.new(
        _hmac_key, normalize_document_number(document_number).encode(), hashlib.sha256
    ).hexdigest()
