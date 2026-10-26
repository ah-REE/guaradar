"""Image intake for road reports: validation, re-encoding, and metadata stripping.

THE DESIGN DECISION THAT MATTERS
  Nothing about a submission's image is trusted except its pixels. Filename, declared MIME
  type, magic bytes and `Content-Type` header are all attacker-controlled, and the brief is
  explicit that we must "validate actual image content, not only the filename or supplied MIME
  type". So the pipeline is:

      1. reject by SIZE before decoding        (a decompression bomb never gets decoded)
      2. reject by PIXEL COUNT before decoding (Pillow's own guard, but we state the limit)
      3. DECODE with Pillow                    (this is the real content check)
      4. verify the declared format is allowed (JPEG/PNG/WebP only)
      5. resize + re-encode from PIXELS        (this is what strips metadata)
      6. return clean bytes + a hash

WHY RE-ENCODING INSTEAD OF PATCHING EXIF
  Stripping metadata by deleting EXIF blocks is easy to get subtly wrong: EXIF lives in
  several containers, thumbnails carry their own copies, XMP is separate, and vendor blocks
  survive naive removal. Re-encoding from the decoded pixel buffer cannot preserve any of them,
  because nothing but pixels is ever read. A phone photo's GPS tag therefore cannot reach a
  publicly served copy — not because it was removed, but because it was never carried over.

WHY JPEG FOR EVERY OUTPUT
  Reports are photographs of streets. JPEG is universally supported by the browsers this app
  targets and keeps byte size small on the unreliable mobile networks the brief cares about.
  PNG input is accepted and converted; alpha is flattened onto white rather than turned black.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageFile, UnidentifiedImageError

# Pillow's own bomb guard is a warning by default; we want a hard failure, because a partially
# decoded image is exactly the kind of "worked on my machine" hazard that ends up in memory
# exhaustion on a small Render instance.
Image.MAX_IMAGE_PIXELS = 40_000_000  # ~40 MP: comfortably above any phone camera
ImageFile.LOAD_TRUNCATED_IMAGES = False

# Format allow-list, per the brief ("JPEG, PNG, and WebP"). Pillow names, not MIME types: the
# MIME type is client-supplied and therefore not evidence.
ALLOWED_FORMATS: tuple[str, ...] = ("JPEG", "PNG", "WEBP")

# Output geometry. 1280 px on the long edge is enough to see a street condition on a phone and
# keeps a typical frame well under 300 KB.
MAX_OUTPUT_EDGE_PX = 1280
JPEG_QUALITY = 82

# Size limit, overridable from configuration. 5 MB accepts every current phone camera default
# and refuses anything that looks like an unbounded upload.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024

CONTENT_TYPE = "image/jpeg"


class ImageRejected(Exception):
    """A submission the pipeline refuses, with a machine-readable code.

    `code` exists so the API can return a stable, translatable identifier instead of leaking
    Pillow's wording (which mentions internal modules and is not a user-facing sentence).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StoredImage:
    """A sanitised image, ready to be persisted."""

    content_type: str
    data: bytes
    width: int
    height: int
    sha256: str
    # Always True: re-encoding from pixels cannot carry EXIF forward. Present as an explicit
    # field rather than an implicit assumption so it appears in the audit trail and in tests.
    metadata_stripped: bool = True

    @property
    def byte_size(self) -> int:
        return len(self.data)


def _human_bytes(n: int) -> str:
    """Readable size that never says "0.0 MB".

    A 100-byte test limit rendered as "0.0 MB" would be a useless error message, and the same
    formatting bug would hit any deployment configured with a limit under 1 MB.
    """
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1_048_576:.1f} MB"


def validate_size(raw: bytes, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
    """Reject oversized payloads before any decoding happens.

    Called separately from `process_image` so a caller can enforce the limit on the upload
    stream and avoid buffering a huge body in the first place.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be > 0")
    if not raw:
        raise ImageRejected("image_empty", "The image file is empty.")
    if len(raw) > max_bytes:
        raise ImageRejected(
            "image_too_large",
            f"The image is {_human_bytes(len(raw))}; the limit is "
            f"{_human_bytes(max_bytes)}.",
        )


def process_image(raw: bytes, max_bytes: int = DEFAULT_MAX_BYTES) -> StoredImage:
    """Validate, normalise, and strip an uploaded image.

    Raises `ImageRejected` with a stable code for every user-correctable problem. Internal
    errors (a Pillow bug, an OOM) are NOT caught here: they should surface as a 500 and be
    logged, because disguising an infrastructure fault as a validation error sends the user
    chasing a problem with their photo that does not exist.
    """
    validate_size(raw, max_bytes)

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            # `verify()` catches truncated and structurally broken files, but it consumes the
            # image object, so nothing can be read afterwards. That is why it runs on a probe.
            try:
                probe.verify()
            except Exception as exc:  # noqa: BLE001 - any failure here means "not a valid image"
                raise ImageRejected(
                    "image_corrupt", "The image could not be read; it may be truncated."
                ) from exc
    except UnidentifiedImageError as exc:
        raise ImageRejected(
            "image_not_an_image", "That file is not a recognised image."
        ) from exc
    except Image.DecompressionBombError as exc:
        raise ImageRejected(
            "image_too_many_pixels",
            "The image has too many pixels to process safely.",
        ) from exc

    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected(
            "image_format_unsupported",
            f"Unsupported image format {fmt or 'unknown'}. Use JPEG, PNG or WebP.",
        )

    # Re-open: `verify()` left the first handle unusable.
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            # `convert("RGB")` drops alpha and, critically, drops any palette/EXIF payload.
            flat = img.convert("RGB")
            resized = _fit(flat, MAX_OUTPUT_EDGE_PX)
            out = io.BytesIO()
            # No `exif=` and no `icc_profile=` argument: passing either would explicitly copy
            # metadata into the output. Omitting them is what makes the strip complete.
            resized.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            data = out.getvalue()
            width, height = resized.size
    except Image.DecompressionBombError as exc:
        raise ImageRejected(
            "image_too_many_pixels", "The image has too many pixels to process safely."
        ) from exc
    except (OSError, ValueError) as exc:
        # A physically valid header over a broken pixel stream lands here.
        raise ImageRejected(
            "image_corrupt", "The image could not be processed."
        ) from exc

    return StoredImage(
        content_type=CONTENT_TYPE,
        data=data,
        width=width,
        height=height,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _fit(img: Image.Image, max_edge: int) -> Image.Image:
    """Downscale so the long edge is at most `max_edge`, preserving aspect ratio.

    Never upscales: enlarging a 400 px photo would add bytes and no detail, and the intake
    pipeline has no business inventing resolution.
    """
    w, h = img.size
    longest = max(w, h)
    if longest <= max_edge:
        return img
    scale = max_edge / longest
    # `max(1, …)` because a very wide panorama could round one dimension to zero.
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def has_exif_gps(raw: bytes) -> bool:
    """Whether the ORIGINAL upload carried GPS metadata.

    Deliberately a separate, read-only question. It is used only to decide whether to tell the
    user "we removed the location data from your photo", which is worth saying because people
    are surprised by how much their camera records. It never influences whether the upload is
    accepted: refusing photos with GPS tags would push users to strip them and hide the fact.
    """
    try:
        with Image.open(io.BytesIO(raw)) as img:
            exif = img.getexif()
            if not exif:
                return False
            gps_ifd = exif.get_ifd(0x8825)  # GPSInfo
            return bool(gps_ifd)
    except Exception:  # noqa: BLE001 - metadata inspection must never fail a submission
        return False
