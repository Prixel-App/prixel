"""Vignettes : on réutilise l'aperçu JPEG que les appareils glissent dans leurs
fichiers (miniature EXIF, aperçu des RAW) plutôt que de décoder l'image."""

import os
import struct

from .categories import extension
from .metadata import TIFF_RAW, _read_ifd

WEB_IMAGES = {"jpg", "jpeg", "png", "gif", "webp", "avif", "bmp"}
PREVIEWABLE = WEB_IMAGES | TIFF_RAW | {"raf"}

_MAX_DIRECT = 25 * 1024 * 1024  # au-delà, on ne renvoie pas le fichier entier
_IDEAL = 1024 * 1024  # un aperçu autour de 1 Mo est net sans être lourd

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
         "webp": "image/webp", "avif": "image/avif", "bmp": "image/bmp"}


def can_preview(name):
    return extension(name) in PREVIEWABLE


def _tiff_candidates(data, base):
    """Blocs JPEG (offset, longueur) déclarés dans les IFD d'un TIFF."""
    if data[:2] == b"II":
        e = "<"
    elif data[:2] == b"MM":
        e = ">"
    else:
        return []
    out = []
    try:
        queue = [struct.unpack_from(e + "I", data, 4)[0]]
        seen = set()
        while queue and len(seen) < 16:
            off = queue.pop(0)
            if not off or off in seen or off + 2 > len(data):
                continue
            seen.add(off)
            tags = _read_ifd(data, off, e)

            def val(tag):
                typ, n, raw = tags[tag]
                return struct.unpack(e + ("H" if typ == 3 else "I"), raw[:2] if typ == 3 else raw)[0]

            if 0x0201 in tags and 0x0202 in tags:
                out.append((base + val(0x0201), val(0x0202)))
            if 0x0111 in tags and 0x0117 in tags and 0x0103 in tags and val(0x0103) in (6, 7) \
                    and tags[0x0111][1] == 1:
                out.append((base + val(0x0111), val(0x0117)))
            if 0x014A in tags:  # SubIFDs (NEF, DNG)
                typ, n, raw = tags[0x014A]
                if n == 1:
                    queue.append(struct.unpack(e + "I", raw)[0])
                else:
                    (ptr,) = struct.unpack(e + "I", raw)
                    queue.extend(struct.unpack_from(e + "%dI" % min(n, 8), data, ptr))
            count = struct.unpack_from(e + "H", data, off)[0]
            nxt = off + 2 + count * 12
            if nxt + 4 <= len(data):
                queue.append(struct.unpack_from(e + "I", data, nxt)[0])
    except (struct.error, KeyError, IndexError):
        pass
    return out


def _jpeg_exif_thumb(head):
    pos = 2
    while pos + 4 <= len(head) and head[pos] == 0xFF:
        marker = head[pos + 1]
        (length,) = struct.unpack_from(">H", head, pos + 2)
        if marker == 0xE1 and head[pos + 4:pos + 10] == b"Exif\x00\x00":
            return [(pos + 10 + o, n) for o, n in _tiff_candidates(head[pos + 10:pos + 2 + length], 0)]
        if marker in (0xDA, 0xD9):
            break
        pos += 2 + length
    return []


def _read_jpeg(fh, offset, length):
    if length <= 0 or length > 40 * 1024 * 1024:
        return None
    fh.seek(offset)
    blob = fh.read(length)
    return blob if blob[:2] == b"\xff\xd8" else None


def preview(path):
    """Renvoie (octets, type MIME) d'une image affichable, ou None."""
    ext = extension(os.path.basename(path))
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(256 * 1024)
        if ext in ("jpg", "jpeg"):
            # La miniature EXIF (≈ 160 px) est floue : on préfère l'image si elle reste légère.
            if size <= 3 * 1024 * 1024:
                fh.seek(0)
                return fh.read(), "image/jpeg"
            for off, n in _jpeg_exif_thumb(head):
                blob = _read_jpeg(fh, off, n)
                if blob:
                    return blob, "image/jpeg"
        if ext in WEB_IMAGES:
            if size <= _MAX_DIRECT:
                fh.seek(0)
                return fh.read(), _MIME[ext]
            return None
        if ext == "raf" and head[:15] == b"FUJIFILMCCD-RAW":
            off, n = struct.unpack_from(">II", head, 84)
            blob = _read_jpeg(fh, off, n)
            return (blob, "image/jpeg") if blob else None
        candidates = [c for c in _tiff_candidates(head, 0) if c[1] > 4096]
        if not candidates:
            return None
        # L'aperçu le plus proche d'1 Mo : assez grand pour être net, assez petit pour être rapide.
        candidates.sort(key=lambda c: abs(c[1] - _IDEAL))
        for off, n in candidates:
            blob = _read_jpeg(fh, off, n)
            if blob:
                return blob, "image/jpeg"
    return None
