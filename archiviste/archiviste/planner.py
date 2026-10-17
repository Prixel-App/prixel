"""Analyse d'un dossier et construction du plan de rangement.

Le plan ne touche à rien : il dit seulement, pour chaque fichier, où il irait.
C'est ce plan que l'on affiche en aperçu, puis que l'exécuteur applique.
"""

import hashlib
import os
import re
from datetime import timedelta

from .categories import MEDIA_CATEGORIES, OTHER, category_for, document_topic
from .metadata import SOURCE_FILE, read_metadata

STATE_DIR = ".archiviste"
DUPLICATES_DIR = "_Doublons"

ACTION_MOVE = "ranger"
ACTION_DUPLICATE = "doublon"
ACTION_IN_PLACE = "déjà rangé"

# Fichiers système sans valeur, jamais déplacés.
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "icon\r", ".localized", "ehthumbs.db"}
# Dossiers que l'on ne parcourt jamais.
IGNORED_DIRS = {
    "$recycle.bin", "system volume information", ".trashes", ".trash", ".spotlight-v100",
    ".fseventsd", ".temporaryitems", ".documentrevisions-v100", "lost+found",
    STATE_DIR,
}
# « Paquets » macOS et bibliothèques : dossiers qui forment un tout et qu'on
# ne doit jamais éparpiller. On les laisse en place.
BUNDLE_SUFFIXES = (
    ".app", ".photoslibrary", ".fcpbundle", ".lrdata", ".lrlibrary", ".imovielibrary",
    ".tvlibrary", ".musiclibrary", ".aplibrary", ".cocatalog", ".cocatalogdb",
    ".dvdmedia", ".bundle", ".framework", ".rtfd", ".sparsebundle", ".git",
    ".logicx", ".band", ".prproj", ".dspproj",
)

DEFAULT_TEMPLATE = "auto"
PLACEHOLDERS = ("categorie", "theme", "annee", "mois", "jour", "seance", "appareil", "extension")


class Options:
    def __init__(
        self,
        source,
        destination,
        copy=False,
        sessions=True,
        session_gap_hours=4.0,
        duplicates=True,
        topics=True,
        template=DEFAULT_TEMPLATE,
        include_hidden=False,
    ):
        self.source = os.path.abspath(source)
        self.destination = os.path.abspath(destination)
        self.copy = copy
        self.sessions = sessions
        self.session_gap_hours = session_gap_hours
        self.duplicates = duplicates
        self.topics = topics
        self.template = template or DEFAULT_TEMPLATE
        self.include_hidden = include_hidden


class Item:
    __slots__ = ("src", "size", "mtime", "category", "topic", "meta", "session", "dest",
                 "action", "duplicate_of")

    def __init__(self, src, size, mtime, category, topic, meta):
        self.src = src
        self.size = size
        self.mtime = mtime
        self.category = category
        self.topic = topic
        self.meta = meta
        self.session = None
        self.dest = None
        self.action = ACTION_MOVE
        self.duplicate_of = None


class Plan:
    def __init__(self, options, items, skipped):
        self.options = options
        self.items = items
        self.skipped = skipped  # [(chemin, raison)]

    def to_apply(self):
        return [i for i in self.items if i.action != ACTION_IN_PLACE]

    def summary(self):
        by_cat = {}
        for item in self.items:
            key = DUPLICATES_DIR if item.action == ACTION_DUPLICATE else item.category
            count, size = by_cat.get(key, (0, 0))
            by_cat[key] = (count + 1, size + item.size)
        return by_cat


# ------------------------------------------------------------------- Parcours

def _is_inside(path, parent):
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:  # lecteurs différents sous Windows
        return False


def scan(options, progress=None):
    """Liste les fichiers à ranger. Renvoie (items, ignorés)."""
    items, skipped = [], []
    dest = options.destination
    nested_dest = dest != options.source and _is_inside(dest, options.source)
    duplicates_dir = os.path.join(dest, DUPLICATES_DIR)
    seen = 0
    for root, dirs, files in os.walk(options.source):
        kept = []
        for d in dirs:
            full = os.path.join(root, d)
            low = d.lower()
            if low in IGNORED_DIRS:
                continue
            if not options.include_hidden and d.startswith("."):
                continue
            if nested_dest and _is_inside(full, dest):
                continue  # ne pas re-ranger ce qui vient d'être rangé
            if os.path.normcase(full) == os.path.normcase(duplicates_dir):
                continue  # les doublons déjà écartés restent où ils sont
            if low.endswith(BUNDLE_SUFFIXES):
                skipped.append((full, "paquet ou bibliothèque laissé intact"))
                continue
            if os.path.islink(full):
                continue
            kept.append(d)
        dirs[:] = sorted(kept)
        for name in sorted(files):
            full = os.path.join(root, name)
            if name.lower() in IGNORED_NAMES:
                continue
            if not options.include_hidden and name.startswith("."):
                continue
            try:
                if os.path.islink(full):
                    skipped.append((full, "raccourci (lien symbolique)"))
                    continue
                st = os.stat(full)
                meta = read_metadata(full, st)
            except OSError as exc:
                skipped.append((full, "illisible : %s" % exc.strerror))
                continue
            cat = category_for(name)
            topic = document_topic(name) if options.topics and cat == "Documents" else None
            items.append(Item(full, st.st_size, st.st_mtime, cat, topic, meta))
            seen += 1
            if progress and seen % 50 == 0:
                progress("Analyse", seen, None)
    if progress:
        progress("Analyse", seen, seen)
    return items, skipped


# ------------------------------------------------------------------- Séances

def assign_sessions(items, gap_hours):
    """Regroupe photos et vidéos en séances : un trou de plus de `gap_hours`
    entre deux prises de vue ouvre une nouvelle séance."""
    media = sorted(
        (i for i in items if i.category in MEDIA_CATEGORIES),
        key=lambda i: i.meta.date,
    )
    gap = timedelta(hours=gap_hours)
    per_day = {}
    current, last = None, None
    for item in media:
        if last is None or item.meta.date - last > gap:
            day = item.meta.date.strftime("%Y-%m-%d")
            per_day[day] = per_day.get(day, 0) + 1
            current = day if per_day[day] == 1 else "%s (%d)" % (day, per_day[day])
        item.session = current
        last = item.meta.date


# ----------------------------------------------------------------- Doublons

def _digest(path, limit=None):
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as fh:
        remaining = limit
        while True:
            chunk = fh.read(1024 * 1024 if remaining is None else min(remaining, 1024 * 1024))
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
                if remaining <= 0:
                    break
    return h.hexdigest()


def same_content(a, b):
    try:
        return os.path.getsize(a) == os.path.getsize(b) and _digest(a) == _digest(b)
    except OSError:
        return False


_COPY_NAME = re.compile(r"(copie|copy|kopie|\(\d+\))", re.IGNORECASE)


def _original_rank(item):
    """Plus la valeur est petite, plus le fichier a l'air d'être l'original."""
    stem = os.path.splitext(os.path.basename(item.src))[0]
    return (item.meta.source == SOURCE_FILE, bool(_COPY_NAME.search(stem)),
            item.meta.date, item.mtime, len(item.src), item.src)


def find_duplicates(items, progress=None):
    """Marque comme doublons les fichiers au contenu strictement identique.
    L'original retenu est celui dont la date est la plus fiable puis la plus ancienne."""
    by_size = {}
    for item in items:
        if item.size > 0:
            by_size.setdefault(item.size, []).append(item)
    candidates = [g for g in by_size.values() if len(g) > 1]
    total = sum(len(g) for g in candidates)
    done = 0
    for group in candidates:
        # Un premier tri rapide sur le début du fichier évite de tout lire.
        by_head = {}
        for item in group:
            try:
                by_head.setdefault(_digest(item.src, 64 * 1024), []).append(item)
            except OSError:
                pass
        for same_head in by_head.values():
            if len(same_head) < 2:
                continue
            by_full = {}
            for item in same_head:
                try:
                    by_full.setdefault(_digest(item.src), []).append(item)
                except OSError:
                    pass
            for twins in by_full.values():
                if len(twins) < 2:
                    continue
                twins.sort(key=_original_rank)
                original = twins[0]
                for twin in twins[1:]:
                    twin.action = ACTION_DUPLICATE
                    twin.duplicate_of = original.src
        done += len(group)
        if progress:
            progress("Recherche des doublons", done, total)


# --------------------------------------------------------------- Destination

def _clean(part):
    bad = '<>:"/\\|?*'
    part = "".join("_" if c in bad or ord(c) < 32 else c for c in str(part)).strip(" .")
    return part or "_"


def folder_parts(item, options):
    d = item.meta.date
    if options.template == DEFAULT_TEMPLATE:
        if item.category in MEDIA_CATEGORIES:
            return [item.category, d.strftime("%Y"), item.session or d.strftime("%Y-%m-%d")]
        if item.topic:
            return [item.category, item.topic, d.strftime("%Y")]
        if item.category == OTHER:
            return [OTHER]
        return [item.category, d.strftime("%Y"), d.strftime("%Y-%m")]
    values = {
        "categorie": item.category,
        "theme": item.topic or "Divers",
        "annee": d.strftime("%Y"),
        "mois": d.strftime("%m"),
        "jour": d.strftime("%d"),
        "seance": item.session or d.strftime("%Y-%m-%d"),
        "appareil": item.meta.camera or "Appareil inconnu",
        "extension": (os.path.splitext(item.src)[1][1:] or "sans extension").upper(),
    }
    path = options.template
    for key, value in values.items():
        path = path.replace("{%s}" % key, _clean(value))
    return [_clean(p) for p in path.replace("\\", "/").split("/") if p.strip()]


def _unique(path, reserved):
    """Ajoute « (2) », « (3) »… tant que le nom est pris (sur le disque ou dans le plan)."""
    base, ext = os.path.splitext(path)
    candidate, n = path, 1
    while os.path.normcase(candidate) in reserved or os.path.lexists(candidate):
        n += 1
        candidate = "%s (%d)%s" % (base, n, ext)
    return candidate


def _already_there(src, target, reserved):
    """Chemin d'un fichier identique déjà présent sous ce nom ou « nom (n) », sinon None."""
    base, ext = os.path.splitext(target)
    candidate, n = target, 1
    while os.path.lexists(candidate):
        if os.path.normcase(candidate) not in reserved and same_content(src, candidate):
            return candidate
        n += 1
        candidate = "%s (%d)%s" % (base, n, ext)
    return None


def assign_destinations(items, options):
    reserved = set()
    # Les fichiers qui ne bougent pas gardent leur place en priorité.
    for item in items:
        if item.action != ACTION_DUPLICATE:
            target = os.path.join(options.destination, *folder_parts(item, options),
                                  os.path.basename(item.src))
            if os.path.normcase(target) == os.path.normcase(item.src):
                item.action = ACTION_IN_PLACE
                item.dest = item.src
                reserved.add(os.path.normcase(target))
    for item in items:
        if item.action == ACTION_IN_PLACE:
            continue
        parts = folder_parts(item, options)
        if item.action == ACTION_DUPLICATE:
            parts = [DUPLICATES_DIR] + parts
        target = os.path.join(options.destination, *parts, os.path.basename(item.src))
        existing = item.action != ACTION_DUPLICATE and _already_there(item.src, target, reserved)
        if existing:
            # Le même fichier est déjà rangé à cet endroit : c'est un doublon.
            item.action = ACTION_DUPLICATE
            item.duplicate_of = existing
            target = os.path.join(options.destination, DUPLICATES_DIR, *parts,
                                  os.path.basename(item.src))
        item.dest = _unique(target, reserved)
        reserved.add(os.path.normcase(item.dest))


# --------------------------------------------------------------------- Entrée

def build_plan(options, progress=None):
    if not os.path.isdir(options.source):
        raise FileNotFoundError("Dossier source introuvable : %s" % options.source)
    items, skipped = scan(options, progress)
    if options.sessions:
        assign_sessions(items, options.session_gap_hours)
    if options.duplicates:
        find_duplicates(items, progress)
    assign_destinations(items, options)
    return Plan(options, items, skipped)
