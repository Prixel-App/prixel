import json
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archiviste.previews import preview  # noqa: E402
from archiviste.server import App, make_handler  # noqa: E402
from test_archiviste import jpeg_with_exif, write  # noqa: E402

FAKE_JPEG = b"\xff\xd8" + b"\x00" * 6000 + b"\xff\xd9"


def raw_with_preview():
    """TIFF minimal dont l'IFD0 déclare un aperçu JPEG (0x0201/0x0202), comme un ARW."""
    ifd = struct.pack("<H", 2)
    ifd += struct.pack("<HHII", 0x0201, 4, 1, 64)
    ifd += struct.pack("<HHII", 0x0202, 4, 1, len(FAKE_JPEG))
    ifd += struct.pack("<I", 0)
    head = b"II*\0" + struct.pack("<I", 8) + ifd
    return head + b"\0" * (64 - len(head)) + FAKE_JPEG


class PreviewTest(unittest.TestCase):
    def test_raw_embedded_jpeg(self):
        p = write(os.path.join(tempfile.mkdtemp(), "x.ARW"), raw_with_preview())
        self.assertEqual(preview(p), (FAKE_JPEG, "image/jpeg"))

    def test_unknown(self):
        p = write(os.path.join(tempfile.mkdtemp(), "x.NEF"), b"rien")
        self.assertIsNone(preview(p))


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        write(os.path.join(self.tmp, "src", "a.jpg"), jpeg_with_exif(datetime(2024, 5, 12, 10, 0)))
        write(os.path.join(self.tmp, "src", "Facture 3.pdf"), b"%PDF")
        self.app = App()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()

    def call(self, path, body=None, token=True, host=None):
        c = HTTPConnection("127.0.0.1", self.httpd.server_address[1])
        headers = {"X-Archiviste": self.app.token} if token else {}
        if host:
            headers["Host"] = host
        c.request("POST" if body is not None else "GET", path,
                  json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        return r.status, r.read()

    def wait(self):
        for _ in range(200):
            status, data = self.call("/api/task")
            snap = json.loads(data)
            if snap["state"] in ("done", "error"):
                return snap
            time.sleep(0.02)
        self.fail("tâche trop longue")

    def test_token_and_host_required(self):
        self.assertEqual(self.call("/api/meta", token=False)[0], 403)
        self.assertEqual(self.call("/api/meta", host="evil.example:80")[0], 403)
        self.assertEqual(self.call("/api/meta")[0], 200)
        self.assertEqual(self.call("/")[0], 200)  # la page elle-même ne contient aucune donnée

    def test_analyse_apply_undo(self):
        src, dst = os.path.join(self.tmp, "src"), os.path.join(self.tmp, "dst")
        status, _ = self.call("/api/analyse", {"source": src, "destination": dst, "copy": False})
        self.assertEqual(status, 200)
        plan = self.wait()["result"]
        dests = sorted(i["dest"].replace(os.sep, "/") for i in plan["items"])
        self.assertEqual(dests, ["Documents/Factures/" + dests[0].split("/")[2] + "/Facture 3.pdf",
                                 "Photos/2024/2024-05-12/a.jpg"])
        img = next(i for i in plan["items"] if i["img"])
        status, data = self.call("/api/thumb?i=%d" % img["i"])
        self.assertEqual((status, data[:2]), (200, b"\xff\xd8"))
        self.call("/api/apply", {})
        result = self.wait()["result"]
        self.assertEqual(result["done"], 2)
        self.assertFalse(os.path.exists(os.path.join(src, "a.jpg")))
        journals = json.loads(self.call("/api/journals?dest=" + dst)[1])
        self.assertEqual(len(journals), 1)
        self.call("/api/undo", {"journal": journals[0]["path"]})
        self.assertEqual(self.wait()["result"]["restored"], 2)
        self.assertTrue(os.path.exists(os.path.join(src, "a.jpg")))

    def test_undo_rejects_foreign_file(self):
        status, _ = self.call("/api/undo", {"journal": os.path.join(self.tmp, "src", "a.jpg")})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
