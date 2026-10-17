import os
import struct
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archiviste.categories import category_for, document_topic  # noqa: E402
from archiviste.executor import apply_plan, list_journals, undo  # noqa: E402
from archiviste.metadata import (SOURCE_EXIF, SOURCE_FILE, SOURCE_NAME, SOURCE_VIDEO,  # noqa: E402
                                 date_from_name, read_metadata)
from archiviste.planner import ACTION_DUPLICATE, ACTION_IN_PLACE, Options, build_plan  # noqa: E402


def tiff_block(date, make="Canon", model="Canon EOS R5"):
    """Bloc TIFF petit-boutiste : IFD0 (Make, Model, ExifIFD) + IFD EXIF (DateTimeOriginal)."""
    make_b, model_b = make.encode() + b"\0", model.encode() + b"\0"
    date_b = date.strftime("%Y:%m:%d %H:%M:%S").encode() + b"\0"
    ifd0_off = 8
    ifd0_size = 2 + 3 * 12 + 4
    data_off = ifd0_off + ifd0_size
    make_off = data_off
    model_off = make_off + len(make_b)
    exif_off = model_off + len(model_b)
    exif_size = 2 + 12 + 4
    date_off = exif_off + exif_size
    out = b"II*\0" + struct.pack("<I", ifd0_off)
    out += struct.pack("<H", 3)
    out += struct.pack("<HHII", 0x010F, 2, len(make_b), make_off)
    out += struct.pack("<HHII", 0x0110, 2, len(model_b), model_off)
    out += struct.pack("<HHII", 0x8769, 4, 1, exif_off)
    out += struct.pack("<I", 0)
    out += make_b + model_b
    out += struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, len(date_b), date_off)
    out += struct.pack("<I", 0) + date_b
    return out


def jpeg_with_exif(date, payload=b""):
    exif = b"Exif\0\0" + tiff_block(date)
    return (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
            + b"\xff\xda\x00\x02" + payload + b"\xff\xd9")


def mp4_with_date(date):
    secs = int((date - datetime(1904, 1, 1)).total_seconds())
    mvhd_body = b"\0\0\0\0" + struct.pack(">II", secs, secs) + b"\0" * 88
    mvhd = struct.pack(">I4s", 8 + len(mvhd_body), b"mvhd") + mvhd_body
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"isom\0\0\0\0"
    mdat = struct.pack(">I4s", 8 + 1000, b"mdat") + b"\0" * 1000
    return ftyp + mdat + moov


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class CategoriesTest(unittest.TestCase):
    def test_extensions(self):
        self.assertEqual(category_for("A.JPG"), "Photos")
        self.assertEqual(category_for("a.cr3"), "Photos RAW")
        self.assertEqual(category_for("rush.MOV"), "Vidéos")
        self.assertEqual(category_for("maquette.psd"), "Création")
        self.assertEqual(category_for("sans_extension"), "Autres")

    def test_topics(self):
        self.assertEqual(document_topic("Facture_2024-003.pdf"), "Factures")
        self.assertEqual(document_topic("CONTRAT cession droits.docx"), "Contrats")
        self.assertEqual(document_topic("Scénario v3.pdf"), "Scénarios")
        self.assertEqual(document_topic("liste courses.txt"), None)
        self.assertEqual(document_topic("export cvs.txt"), None)  # « cv » mot entier seulement


class MetadataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_jpeg_exif(self):
        p = write(os.path.join(self.tmp, "x.jpg"), jpeg_with_exif(datetime(2021, 6, 3, 18, 45, 10)))
        m = read_metadata(p)
        self.assertEqual(m.source, SOURCE_EXIF)
        self.assertEqual(m.date, datetime(2021, 6, 3, 18, 45, 10))
        self.assertEqual(m.camera, "Canon EOS R5")

    def test_tiff_raw(self):
        p = write(os.path.join(self.tmp, "x.NEF"), tiff_block(datetime(2019, 1, 2, 3, 4, 5)))
        self.assertEqual(read_metadata(p).date, datetime(2019, 1, 2, 3, 4, 5))

    def test_mp4(self):
        p = write(os.path.join(self.tmp, "x.mp4"), mp4_with_date(datetime(2022, 8, 9, 10, 11, 12)))
        m = read_metadata(p)
        self.assertEqual((m.source, m.date), (SOURCE_VIDEO, datetime(2022, 8, 9, 10, 11, 12)))

    def test_name_patterns(self):
        self.assertEqual(date_from_name("IMG_20230512_143012.jpg"), datetime(2023, 5, 12, 14, 30, 12))
        self.assertEqual(date_from_name("IMG-20230512-WA0001.jpg"), datetime(2023, 5, 12))
        self.assertEqual(date_from_name("Capture 2024-01-31 at 09.15.02.png"), datetime(2024, 1, 31, 9, 15, 2))
        self.assertIsNone(date_from_name("DSC_1234.jpg"))
        self.assertIsNone(date_from_name("ref 20231345.pdf"))

    def test_fallbacks(self):
        p = write(os.path.join(self.tmp, "scan_2020-02-02.pdf"))
        self.assertEqual(read_metadata(p).source, SOURCE_NAME)
        p = write(os.path.join(self.tmp, "broken.jpg"), b"pas une image")
        self.assertEqual(read_metadata(p).source, SOURCE_FILE)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "vrac")
        self.dst = os.path.join(self.tmp, "range")
        s = self.src
        write(os.path.join(s, "a.jpg"), jpeg_with_exif(datetime(2024, 5, 12, 10, 0), b"A"))
        write(os.path.join(s, "sub", "b.jpg"), jpeg_with_exif(datetime(2024, 5, 12, 11, 30), b"B"))
        # Même jour mais 7 h plus tard : nouvelle séance.
        write(os.path.join(s, "c.jpg"), jpeg_with_exif(datetime(2024, 5, 12, 18, 30), b"C"))
        # Copie exacte de a.jpg sous un autre nom.
        write(os.path.join(s, "old", "a copie.jpg"), jpeg_with_exif(datetime(2024, 5, 12, 10, 0), b"A"))
        write(os.path.join(s, "clip.mp4"), mp4_with_date(datetime(2024, 5, 12, 10, 15)))
        write(os.path.join(s, "Facture 12.pdf"), b"%PDF facture")
        write(os.path.join(s, ".DS_Store"), b"junk")
        write(os.path.join(s, "Photos.photoslibrary", "db"), b"ne pas toucher")
        # Deux fichiers différents qui arriveraient au même endroit.
        write(os.path.join(s, "x", "notes.txt"), b"un")
        write(os.path.join(s, "y", "notes.txt"), b"deux")
        for name in ("notes.txt",):
            for d in ("x", "y"):
                os.utime(os.path.join(s, d, name), (1700000000, 1700000000))

    def rel(self, item):
        return os.path.relpath(item.dest, self.dst).replace(os.sep, "/")

    def plan(self, **kw):
        return build_plan(Options(self.src, self.dst, **kw))

    def by_name(self, plan):
        return {os.path.relpath(i.src, self.src).replace(os.sep, "/"): i for i in plan.items}

    def test_layout(self):
        items = self.by_name(self.plan())
        self.assertNotIn(".DS_Store", items)
        self.assertNotIn("Photos.photoslibrary/db", items)
        self.assertEqual(self.rel(items["a.jpg"]), "Photos/2024/2024-05-12/a.jpg")
        self.assertEqual(self.rel(items["sub/b.jpg"]), "Photos/2024/2024-05-12/b.jpg")
        self.assertEqual(self.rel(items["c.jpg"]), "Photos/2024/2024-05-12 (2)/c.jpg")
        self.assertEqual(self.rel(items["clip.mp4"]), "Vidéos/2024/2024-05-12/clip.mp4")
        self.assertTrue(self.rel(items["Facture 12.pdf"]).startswith("Documents/Factures/"))
        dup = items["old/a copie.jpg"]
        self.assertEqual(dup.action, ACTION_DUPLICATE)
        self.assertTrue(self.rel(dup).startswith("_Doublons/Photos/"))
        notes = sorted(self.rel(items[k]) for k in ("x/notes.txt", "y/notes.txt"))
        self.assertEqual(notes, ["Documents/2023/2023-11/notes (2).txt",
                                 "Documents/2023/2023-11/notes.txt"])

    def test_original_preferred_over_copy(self):
        write(os.path.join(self.src, "z", "DSC_0042.jpg"), b"meme contenu")
        write(os.path.join(self.src, "a", "DSC_0042 - Copie.jpg"), b"meme contenu")
        items = self.by_name(self.plan())
        self.assertEqual(items["a/DSC_0042 - Copie.jpg"].action, ACTION_DUPLICATE)
        self.assertNotEqual(items["z/DSC_0042.jpg"].action, ACTION_DUPLICATE)

    def test_custom_template(self):
        items = self.by_name(self.plan(template="{annee}/{seance}/{categorie}", sessions=False))
        self.assertEqual(self.rel(items["c.jpg"]), "2024/2024-05-12/Photos/c.jpg")

    def test_apply_undo_move(self):
        before = sorted(os.path.relpath(os.path.join(r, f), self.src)
                        for r, _, fs in os.walk(self.src) for f in fs)
        plan = self.plan()
        journal, done, errors = apply_plan(plan)
        self.assertEqual(errors, [])
        self.assertEqual(done, len(plan.items))
        self.assertTrue(os.path.exists(os.path.join(self.dst, "Photos", "2024", "2024-05-12", "a.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.src, "a.jpg")))
        # Relancer sur le dossier rangé ne change plus rien.
        again = build_plan(Options(self.dst, self.dst))
        self.assertTrue(all(i.action == ACTION_IN_PLACE for i in again.items))
        self.assertEqual(list_journals(self.dst), [journal])
        restored, errors = undo(journal)
        self.assertEqual((restored, errors), (done, []))
        after = sorted(os.path.relpath(os.path.join(r, f), self.src)
                       for r, _, fs in os.walk(self.src) for f in fs)
        self.assertEqual(before, after)
        self.assertEqual(list_journals(self.dst), [])
        self.assertFalse(os.path.exists(os.path.join(self.dst, "Photos")))

    def test_copy_keeps_originals(self):
        _, done, _ = apply_plan(self.plan(copy=True))
        self.assertTrue(os.path.exists(os.path.join(self.src, "a.jpg")))
        # Une seconde passe reconnaît les fichiers déjà copiés comme doublons.
        second = self.plan(copy=True)
        self.assertTrue(all(i.action == ACTION_DUPLICATE for i in second.items))

    def test_in_place(self):
        apply_plan(build_plan(Options(self.src, self.src)))
        again = build_plan(Options(self.src, self.src))
        self.assertTrue(all(i.action == ACTION_IN_PLACE for i in again.items))
        self.assertEqual(len(again.to_apply()), 0)


if __name__ == "__main__":
    unittest.main()
