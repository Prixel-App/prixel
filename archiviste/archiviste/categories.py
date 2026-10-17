"""Reconnaissance du type de fichier : extension, puis indices dans le nom."""

import re
import unicodedata

# Extensions (en minuscules, sans le point) regroupées par catégorie.
CATEGORIES = {
    "Photos": {
        "jpg", "jpeg", "png", "heic", "heif", "tif", "tiff", "webp", "gif", "bmp",
        "avif",
    },
    "Photos RAW": {
        "cr2", "cr3", "crw", "nef", "nrw", "arw", "srf", "sr2", "dng", "raf", "orf",
        "rw2", "pef", "srw", "x3f", "iiq", "3fr", "fff", "erf", "mos", "rwl",
    },
    "Vidéos": {
        "mp4", "mov", "m4v", "avi", "mkv", "mts", "m2ts", "mxf", "wmv", "flv", "webm",
        "3gp", "mpg", "mpeg", "braw", "r3d", "insv",
    },
    "Audio": {"wav", "mp3", "aac", "m4a", "flac", "aif", "aiff", "ogg", "wma", "opus"},
    "Documents": {"pdf", "doc", "docx", "odt", "rtf", "txt", "md", "pages", "epub"},
    "Tableurs": {"xls", "xlsx", "ods", "csv", "numbers"},
    "Présentations": {"ppt", "pptx", "odp", "key"},
    "Création": {
        "psd", "psb", "ai", "eps", "svg", "indd", "idml", "xd", "fig", "sketch",
        "afphoto", "afdesign", "afpub", "xmp", "lrcat", "cube", "lut",
        "prproj", "aep", "drp", "fcpxml", "otio", "edl",
    },
    "Polices": {"ttf", "otf", "woff", "woff2"},
    "Archives": {"zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "dmg", "iso"},
    "Code": {
        "py", "js", "jsx", "ts", "tsx", "html", "css", "json", "xml", "yml", "yaml",
        "sh", "bat", "php", "rb", "java", "c", "cpp", "h", "go", "rs", "sql",
    },
    "Logiciels": {"exe", "msi", "pkg", "app", "apk", "deb", "rpm"},
}

OTHER = "Autres"

# Catégories dont les fichiers portent une date de prise de vue fiable et que
# l'on regroupe par séance plutôt que par mois.
MEDIA_CATEGORIES = {"Photos", "Photos RAW", "Vidéos"}

_EXT_INDEX = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}

# Sous-classement des documents d'après des mots du nom de fichier.
# L'ordre compte : le premier thème reconnu l'emporte.
DOCUMENT_TOPICS = [
    ("Factures", ["facture", "invoice", "proforma", "pro-forma", "avoir"]),
    ("Devis", ["devis", "quote", "quotation", "estimate"]),
    ("Contrats", ["contrat", "contract", "cession", "convention", "accord", "nda"]),
    ("Autorisations", ["release", "autorisation", "droit a l'image", "droit-image"]),
    ("Banque", ["releve", "rib", "iban", "bank", "banque", "virement"]),
    ("Impôts", ["impot", "tax", "fiscal", "urssaf", "tva", "declaration"]),
    ("Administratif", ["attestation", "certificat", "passeport", "identite", "cni", "kbis", "siret"]),
    ("Scénarios", ["scenario", "script", "screenplay", "synopsis", "storyboard", "treatment", "note d'intention"]),
    ("Écrits", ["manuscrit", "chapitre", "nouvelle", "roman", "poeme", "texte", "brouillon"]),
    ("Présentations", ["moodboard", "portfolio", "book", "dossier de presse", "presskit", "deck"]),
    ("CV", ["cv", "resume", "curriculum"]),
]


def extension(name):
    """Extension en minuscules, sans le point ('' si absente)."""
    dot = name.rfind(".")
    if dot <= 0:
        return ""
    return name[dot + 1:].lower()


def category_for(name):
    return _EXT_INDEX.get(extension(name), OTHER)


def _normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def document_topic(name):
    """Thème d'un document deviné d'après son nom, ou None."""
    stem = _normalize(name.rsplit(".", 1)[0])
    # On compare mot à mot pour éviter que « cv » soit trouvé dans « cvs ».
    words = " " + re.sub(r"[^a-z0-9']+", " ", stem) + " "
    for topic, keywords in DOCUMENT_TOPICS:
        for kw in keywords:
            if " " + re.sub(r"[^a-z0-9']+", " ", kw) + " " in words:
                return topic
    return None
