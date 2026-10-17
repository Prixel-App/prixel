"""Lecture de la date de création réelle d'un fichier, sans dépendance externe.

Par ordre de fiabilité :
  1. EXIF (JPEG, TIFF et RAW basés sur TIFF, RAF, CR3, HEIC)
  2. Métadonnées vidéo (MP4, MOV et dérivés : atome « mvhd »)
  3. Une date écrite dans le nom du fichier (IMG_20240512_143000.jpg…)
  4. La date du fichier sur le disque (la plus ancienne connue)
"""

import os
import re
import struct
from datetime import datetime, timedelta

from .categories import extension

SOURCE_EXIF = "exif"
SOURCE_VIDEO = "vidéo"
SOURCE_NAME = "nom"
SOURCE_FILE = "disque"

TIFF_RAW = {
    "tif", "tiff", "dng", "cr2", "nef", "nrw", "arw", "srf", "sr2", "orf", "rw2",
    "pef", "srw", "iiq", "3fr", "fff", "erf", "mos", "rwl", "x3f",
}
BMFF_VIDEO = {"mp4", "mov", "m4v", "3gp", "insv"}
HEIF = {"heic", "heif", "avif"}

_HEADER_BYTES = 1024 * 1024  # 1 Mo suffit pour les métadonnées de presque tous les formats
_EPOCH_1904 = datetime(1904, 1, 1)
_MIN_YEAR = 1980  # en deçà, la date est presque toujours une horloge non réglée


class Metadata:
    __slots__ = ("date", "source", "camera")

    def __init__(self, date, source, camera=None):
        self.date = date
        self.source = source
        self.camera = camera


# --------------------------------------------------------------------------- EXIF

def _parse_exif_datetime(raw):
    try:
        text = raw.split(b"\x00", 1)[0].decode("ascii").strip()
        dt = datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, UnicodeDecodeError):
        return None
    return dt if dt.year >= _MIN_YEAR else None


def _read_ifd(data, offset, endian):
    """Renvoie {tag: (type, count, valeur_ou_offset_brut)} pour un IFD TIFF."""
    entries = {}
    if offset + 2 > len(data):
        return entries
    (count,) = struct.unpack_from(endian + "H", data, offset)
    for i in range(min(count, 512)):
        pos = offset + 2 + i * 12
        if pos + 12 > len(data):
            break
        tag, typ, n = struct.unpack_from(endian + "HHI", data, pos)
        entries[tag] = (typ, n, data[pos + 8:pos + 12])
    return entries


def _ifd_value(data, entry, endian):
    typ, n, raw = entry
    if typ == 2:  # ASCII
        if n <= 4:
            return raw[:n]
        (off,) = struct.unpack(endian + "I", raw)
        return data[off:off + n]
    if typ == 4:  # LONG
        return struct.unpack(endian + "I", raw)[0]
    if typ == 3:  # SHORT
        return struct.unpack(endian + "H", raw[:2])[0]
    return None


def parse_tiff(data):
    """Extrait (date, appareil) d'un bloc TIFF/EXIF commençant par II* ou MM*."""
    if len(data) < 8:
        return None, None
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        return None, None
    try:
        (ifd0,) = struct.unpack_from(endian + "I", data, 4)
        tags = _read_ifd(data, ifd0, endian)
        make = _ifd_value(data, tags[0x010F], endian) if 0x010F in tags else b""
        model = _ifd_value(data, tags[0x0110], endian) if 0x0110 in tags else b""
        date = None
        if 0x8769 in tags:
            exif = _read_ifd(data, _ifd_value(data, tags[0x8769], endian), endian)
            for tag in (0x9003, 0x9004):  # DateTimeOriginal, DateTimeDigitized
                if tag in exif:
                    date = _parse_exif_datetime(_ifd_value(data, exif[tag], endian) or b"")
                    if date:
                        break
        if not date and 0x0132 in tags:
            date = _parse_exif_datetime(_ifd_value(data, tags[0x0132], endian) or b"")
    except (struct.error, KeyError, TypeError, IndexError):
        return None, None
    return date, _camera_name(make, model)


def _camera_name(make, model):
    make = (make or b"").split(b"\x00", 1)[0].decode("latin-1").strip()
    model = (model or b"").split(b"\x00", 1)[0].decode("latin-1").strip()
    if make and model.lower().startswith(make.split()[0].lower()):
        name = model  # « Canon Canon EOS R5 » → « Canon EOS R5 »
    else:
        name = (make + " " + model).strip()
    return name or None


def _exif_from_jpeg(data):
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None, None
        marker = data[pos + 1]
        (length,) = struct.unpack_from(">H", data, pos + 2)
        if marker == 0xE1 and data[pos + 4:pos + 10] == b"Exif\x00\x00":
            return parse_tiff(data[pos + 10:pos + 2 + length])
        if marker in (0xDA, 0xD9):  # début de l'image : plus de métadonnées après
            return None, None
        pos += 2 + length
    return None, None


def _exif_by_scan(data):
    """Repli pour HEIC et formats exotiques : cherche un bloc « Exif\\0\\0 »."""
    idx = data.find(b"Exif\x00\x00")
    while idx != -1:
        date, cam = parse_tiff(data[idx + 6:])
        if date:
            return date, cam
        idx = data.find(b"Exif\x00\x00", idx + 1)
    return None, None


# ----------------------------------------------------------------- ISO BMFF (MP4)

def _boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            (size,) = struct.unpack_from(">Q", data, pos + 8)
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield kind, pos + header, min(pos + size, end)
        pos += size


_CANON_CR3_UUID = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")


def _bmff_metadata(path):
    """Lit la date (mvhd) d'un MP4/MOV, et l'EXIF d'un CR3."""
    with open(path, "rb") as fh:
        top = []
        # Parcourt les boîtes de premier niveau sans charger « mdat » en mémoire.
        while True:
            head = fh.read(16)
            if len(head) < 8:
                break
            size, kind = struct.unpack_from(">I4s", head)
            header = 8
            if size == 1 and len(head) == 16:
                (size,) = struct.unpack_from(">Q", head, 8)
                header = 16
            if kind == b"moov":
                fh.seek(-len(head) + header, 1)
                top.append(fh.read(min(size - header, 32 * 1024 * 1024)))
                break
            if size == 0 or size < header:
                break
            fh.seek(size - len(head), 1)
    if not top:
        return None, None
    moov = top[0]
    date = camera = None
    for kind, start, end in _boxes(moov):
        if kind == b"uuid" and moov[start:start + 16] == _CANON_CR3_UUID:
            for sub, s, e in _boxes(moov, start + 16, end):
                if sub in (b"CMT1", b"CMT2"):
                    d, c = parse_tiff(moov[s:e])
                    camera = camera or c
                    if sub == b"CMT2" and d:
                        date = d
                    date = date or d
        elif kind == b"mvhd" and not date:
            version = moov[start]
            try:
                if version == 1:
                    (secs,) = struct.unpack_from(">Q", moov, start + 4)
                else:
                    (secs,) = struct.unpack_from(">I", moov, start + 4)
            except struct.error:
                continue
            if secs:
                d = _EPOCH_1904 + timedelta(seconds=secs)
                if d.year >= _MIN_YEAR:
                    date = d
    return date, camera


# ------------------------------------------------------------------ Nom de fichier

_NAME_DATE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])"
    r"(?:[-_ Tt.]?(?:at )?([01]\d|2[0-3])[-_.:h]?([0-5]\d)[-_.:m]?([0-5]\d)?)?(?!\d)"
)


def date_from_name(name):
    for m in _NAME_DATE.finditer(name):
        y, mo, d, h, mi, s = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
        except ValueError:
            continue
        if _MIN_YEAR <= dt.year <= datetime.now().year + 1:
            return dt
    return None


# ------------------------------------------------------------------------ Entrée

def _file_date(st):
    stamps = [st.st_mtime]
    birth = getattr(st, "st_birthtime", None)  # macOS, Windows
    if birth:
        stamps.append(birth)
    return datetime.fromtimestamp(min(stamps))


def read_metadata(path, st=None):
    """Meilleure date connue pour ce fichier, avec sa provenance."""
    st = st or os.stat(path)
    name = os.path.basename(path)
    ext = extension(name)
    date = camera = None
    source = None
    try:
        if ext in BMFF_VIDEO or ext == "cr3":
            date, camera = _bmff_metadata(path)
            source = SOURCE_EXIF if ext == "cr3" else SOURCE_VIDEO
        else:
            if ext in ("jpg", "jpeg") or ext in TIFF_RAW or ext in HEIF or ext == "raf":
                with open(path, "rb") as fh:
                    head = fh.read(_HEADER_BYTES)
                if head[:2] == b"\xff\xd8":
                    date, camera = _exif_from_jpeg(head)
                elif ext == "raf" and head[:15] == b"FUJIFILMCCD-RAW":
                    (jpg_off,) = struct.unpack_from(">I", head, 84)
                    date, camera = _exif_from_jpeg(head[jpg_off:])
                elif head[:2] in (b"II", b"MM"):
                    date, camera = parse_tiff(head)
                if not date:
                    date, camera = _exif_by_scan(head)
                source = SOURCE_EXIF
    except (OSError, struct.error, ValueError):
        date = None
    if date:
        return Metadata(date, source, camera)
    named = date_from_name(name)
    if named:
        return Metadata(named, SOURCE_NAME, camera)
    return Metadata(_file_date(st), SOURCE_FILE, camera)
