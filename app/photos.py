"""Contact photos (C-09): validated, resized to at most 512 px, EXIF stripped (ADR-0011)."""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.contacts import ContactError
from app.models import Contact, ContactPhoto

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SIDE = 512
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs


def process_image(data: bytes) -> tuple[bytes, str]:
    """Return (image bytes, content type). Re-encoding drops EXIF/GPS metadata."""
    if not data:
        raise ContactError("Choose an image file", "photo")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ContactError("Photo is larger than 10 MB", "photo")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in {"JPEG", "PNG", "WEBP", "GIF", "HEIC", "MPO"}:
                raise ContactError("Use a JPEG, PNG, WebP or GIF image", "photo")
            img.seek(0)
            image = ImageOps.exif_transpose(img)  # respect phone camera rotation
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            out = io.BytesIO()
            if has_alpha:
                image.convert("RGBA").save(out, "PNG", optimize=True)
                return out.getvalue(), "image/png"
            image.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
            return out.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ContactError("That file is not an image this app can read", "photo") from exc


def _expire_contact_photo(session: Session, contact_id: int) -> None:
    """Keep an already-loaded Contact.photo in step with the change."""
    contact = session.get(Contact, contact_id)
    if contact is not None:
        session.expire(contact, ["photo"])


def set_photo(session: Session, contact_id: int, data: bytes) -> ContactPhoto:
    payload, content_type = process_image(data)
    photo = session.get(ContactPhoto, contact_id)
    if photo is None:
        photo = ContactPhoto(contact_id=contact_id, content_type=content_type, data=payload)
        session.add(photo)
    else:
        photo.content_type = content_type
        photo.data = payload
    session.flush()
    _expire_contact_photo(session, contact_id)
    return photo


def remove_photo(session: Session, contact_id: int) -> None:
    photo = session.get(ContactPhoto, contact_id)
    if photo is not None:
        session.delete(photo)
        session.flush()
        _expire_contact_photo(session, contact_id)
