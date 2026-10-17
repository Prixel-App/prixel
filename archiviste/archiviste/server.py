"""Interface moderne : un petit serveur local qui sert la page `web/index.html`
et ouvre une fenêtre d'application (Chrome ou Edge en mode « app »).

Le serveur n'écoute que sur 127.0.0.1 et exige un jeton secret, tiré au
hasard à chaque lancement : aucune page web ni autre machine ne peut
lui demander de déplacer des fichiers.
"""

import io
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .categories import CATEGORIES, MEDIA_CATEGORIES, OTHER
from .executor import MODE_COPY, apply_plan, list_journals, undo
from .planner import ACTION_DUPLICATE, ACTION_IN_PLACE, DUPLICATES_DIR, Options, build_plan
from .previews import can_preview, preview
from .report import write_csv

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
# La fenêtre fermée, le serveur s'arrête de lui-même. Le délai est large car un
# navigateur ralentit les minuteries d'une fenêtre réduite (un signal par minute).
IDLE_EXIT_SECONDS = 180


class Task:
    """Une seule opération à la fois : analyse, rangement ou annulation."""

    def __init__(self):
        self.lock = threading.Lock()
        self.kind = None
        self.state = "idle"  # idle | running | done | error
        self.stage = ""
        self.done = 0
        self.total = None
        self.result = None
        self.error = None

    def start(self, kind, work):
        with self.lock:
            if self.state == "running":
                return False
            self.kind, self.state, self.stage = kind, "running", ""
            self.done, self.total, self.result, self.error = 0, None, None, None

        def progress(stage, done, total):
            self.stage, self.done, self.total = stage, done, total

        def run():
            try:
                self.result = work(progress)
                self.state = "done"
            except Exception as exc:  # renvoyé à l'interface plutôt que perdu
                self.error = str(exc) or exc.__class__.__name__
                self.state = "error"
        threading.Thread(target=run, daemon=True).start()
        return True

    def snapshot(self):
        return {"kind": self.kind, "state": self.state, "stage": self.stage,
                "done": self.done, "total": self.total, "error": self.error}


class App:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.task = Task()
        self.plan = None
        self.last_seen = time.time()

    # ------------------------------------------------------------ Dossiers

    @staticmethod
    def places():
        home = os.path.expanduser("~")
        out = [{"name": "Accueil", "path": home, "kind": "home"}]
        for sub, label in (("Desktop", "Bureau"), ("Pictures", "Images"), ("Movies", "Vidéos"),
                           ("Videos", "Vidéos"), ("Documents", "Documents"),
                           ("Downloads", "Téléchargements")):
            p = os.path.join(home, sub)
            if os.path.isdir(p) and not any(o["name"] == label for o in out):
                out.append({"name": label, "path": p, "kind": "folder"})
        if os.name == "nt":
            for letter in string.ascii_uppercase:
                p = letter + ":\\"
                if os.path.exists(p):
                    out.append({"name": "Disque " + letter + ":", "path": p, "kind": "drive"})
        else:
            for base in ("/Volumes", "/media/" + os.environ.get("USER", ""), "/mnt"):
                if os.path.isdir(base):
                    for name in sorted(os.listdir(base)):
                        p = os.path.join(base, name)
                        if os.path.isdir(p) and not name.startswith("."):
                            out.append({"name": name, "path": p, "kind": "drive"})
        return out

    @staticmethod
    def listdir(path):
        path = os.path.abspath(os.path.expanduser(path or "~"))
        if not os.path.isdir(path):
            raise FileNotFoundError("Dossier introuvable : %s" % path)
        dirs, files = [], 0
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith(".") or entry.name.startswith("$"):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append(entry.name)
                    else:
                        files += 1
                except OSError:
                    pass
        dirs.sort(key=str.lower)
        parent = os.path.dirname(path.rstrip(os.sep)) or None
        if parent == path:
            parent = None
        return {"path": path, "parent": parent, "dirs": dirs, "files": files, "sep": os.sep}

    # ---------------------------------------------------------------- Plan

    def plan_json(self):
        plan = self.plan
        o = plan.options
        items = []
        for idx, it in enumerate(plan.items):
            dup = None
            if it.duplicate_of:
                base = o.source if it.duplicate_of.startswith(o.source) else o.destination
                dup = os.path.relpath(it.duplicate_of, base)
            items.append({
                "i": idx,
                "src": os.path.relpath(it.src, o.source),
                "dest": os.path.relpath(it.dest, o.destination),
                "cat": it.category,
                "topic": it.topic,
                "action": it.action,
                "date": it.meta.date.strftime("%Y-%m-%d %H:%M"),
                "ds": it.meta.source,
                "size": it.size,
                "cam": it.meta.camera,
                "dup": dup,
                "img": can_preview(it.src),
            })
        return {
            "source": o.source,
            "destination": o.destination,
            "sep": os.sep,
            "copy": o.copy,
            "items": items,
            "skipped": [{"path": os.path.relpath(p, o.source), "why": w} for p, w in plan.skipped],
            "sessions": len({i.session for i in plan.items if i.session}),
        }

    def start_analyse(self, body):
        source = body.get("source") or ""
        dest = body.get("destination") or source
        opts = Options(
            source, dest, copy=bool(body.get("copy", True)),
            sessions=bool(body.get("sessions", True)),
            session_gap_hours=float(body.get("gap", 4)),
            duplicates=bool(body.get("duplicates", True)),
            topics=bool(body.get("topics", True)),
            template=body.get("template") or "auto",
        )
        self.plan = None

        def work(progress):
            self.plan = build_plan(opts, progress)
            return self.plan_json()
        return self.task.start("analyse", work)

    def start_apply(self):
        plan = self.plan
        if plan is None:
            raise ValueError("Aucune analyse en cours.")

        def work(progress):
            journal, done, errors = apply_plan(plan, progress)
            self.plan = None
            return {"journal": journal, "done": done, "errors": errors[:200],
                    "error_count": len(errors), "destination": plan.options.destination,
                    "copy": plan.options.copy}
        return self.task.start("apply", work)

    @staticmethod
    def journals(destination):
        out = []
        for path in list_journals(destination)[:20]:
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = [json.loads(l) for l in fh if l.strip()]
            except (OSError, ValueError):
                continue
            head = lines[0] if lines else {}
            out.append({"path": path, "date": head.get("debut", ""), "copy": head.get("mode") == MODE_COPY,
                        "source": head.get("source", ""), "count": max(len(lines) - 1, 0)})
        return out

    def start_undo(self, journal):
        if not journal or not os.path.isfile(journal) \
                or os.path.basename(os.path.dirname(journal)) != ".archiviste":
            raise ValueError("Journal introuvable.")

        def work(progress):
            restored, errors = undo(journal, progress)
            return {"restored": restored, "errors": errors[:200], "error_count": len(errors)}
        return self.task.start("undo", work)

    def thumb(self, idx):
        plan = self.plan
        if plan is None or not 0 <= idx < len(plan.items):
            return None
        return preview(plan.items[idx].src)

    @staticmethod
    def reveal(path):
        """Montre un dossier dans le Finder ou l'Explorateur."""
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Archiviste/" + __version__

        def log_message(self, *args):
            pass

        # ------------------------------------------------------- Réponses

        def _send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=600" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, query):
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False  # protège contre le « DNS rebinding »
            token = self.headers.get("X-Archiviste") or (query.get("t") or [""])[0]
            return secrets.compare_digest(token, app.token)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        # ---------------------------------------------------------- Routes

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if not self._authorized(q):
                return self._send(403, {"error": "Accès refusé."})
            app.last_seen = time.time()
            try:
                if url.path == "/api/ping":
                    return self._send(200, {"ok": True, "version": __version__})
                if url.path == "/api/meta":
                    return self._send(200, {
                        "version": __version__, "places": app.places(),
                        "categories": list(CATEGORIES) + [OTHER],
                        "media": sorted(MEDIA_CATEGORIES), "duplicates": DUPLICATES_DIR,
                        "actions": {"dup": ACTION_DUPLICATE, "inplace": ACTION_IN_PLACE},
                    })
                if url.path == "/api/fs":
                    return self._send(200, app.listdir((q.get("path") or [""])[0]))
                if url.path == "/api/task":
                    snap = app.task.snapshot()
                    if snap["state"] == "done":
                        snap["result"] = app.task.result
                    return self._send(200, snap)
                if url.path == "/api/journals":
                    return self._send(200, app.journals((q.get("dest") or [""])[0]))
                if url.path == "/api/thumb":
                    found = app.thumb(int((q.get("i") or ["-1"])[0]))
                    if not found:
                        return self._send(404, b"", "text/plain")
                    return self._send(200, found[0], found[1], cache=True)
                if url.path == "/api/plan.csv":
                    if app.plan is None:
                        return self._send(404, {"error": "Aucune analyse."})
                    buf = io.StringIO()
                    write_csv(app.plan, buf)
                    data = buf.getvalue().encode("utf-8-sig")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="plan-de-rangement.csv"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return None
            except (OSError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(404, {"error": "Introuvable."})

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorized(parse_qs(url.query)):
                return self._send(403, {"error": "Accès refusé."})
            app.last_seen = time.time()
            try:
                body = self._body()
                if url.path == "/api/analyse":
                    ok = app.start_analyse(body)
                elif url.path == "/api/apply":
                    ok = app.start_apply()
                elif url.path == "/api/undo":
                    ok = app.start_undo(body.get("journal"))
                elif url.path == "/api/reveal":
                    app.reveal(body.get("path") or "")
                    ok = True
                elif url.path == "/api/mkdir":
                    path = os.path.join(body.get("parent") or "", body.get("name") or "")
                    os.makedirs(path, exist_ok=False)
                    ok = True
                else:
                    return self._send(404, {"error": "Introuvable."})
            except (OSError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})
            if not ok:
                return self._send(409, {"error": "Une opération est déjà en cours."})
            return self._send(200, {"ok": True})

    return Handler


def _app_window(url):
    """Ouvre une fenêtre sans barre d'adresse si Chrome ou Edge est présent."""
    candidates = []
    if sys.platform == "darwin":
        for name in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            p = "/Applications/%s.app/Contents/MacOS/%s" % (name, name)
            candidates.append(p)
    elif os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            candidates += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                           os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")]
    else:
        candidates += [shutil.which(n) or "" for n in
                       ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]
    profile = os.path.join(os.path.expanduser("~"), ".archiviste", "fenetre")
    for exe in candidates:
        if exe and os.path.isfile(exe):
            try:
                subprocess.Popen([exe, "--app=" + url, "--user-data-dir=" + profile,
                                  "--window-size=1360,880", "--no-first-run",
                                  "--no-default-browser-check"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
    return webbrowser.open(url)


def serve(open_window=True, port=0):
    app = App()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = "http://127.0.0.1:%d/?t=%s" % (httpd.server_address[1], app.token)
    print("Archiviste est ouvert dans sa fenêtre.")
    print("Si elle ne s'affiche pas, ouvrez : " + url)
    sys.stdout.flush()
    if open_window:
        threading.Timer(0.3, _app_window, args=(url,)).start()

    def watchdog():
        while True:
            time.sleep(5)
            idle = time.time() - app.last_seen
            if open_window and idle > IDLE_EXIT_SECONDS and app.task.state != "running":
                httpd.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
