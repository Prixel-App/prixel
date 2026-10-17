"""Application du plan, avec un journal qui permet de tout annuler.

Règles de sécurité :
  - aucun fichier n'est jamais supprimé ni écrasé ;
  - chaque opération est écrite dans le journal au moment où elle est faite,
    si bien qu'une coupure en plein travail reste annulable ;
  - en mode copie, l'original n'est pas touché.
"""

import json
import os
import shutil
from datetime import datetime

from .planner import STATE_DIR

MODE_MOVE = "déplacement"
MODE_COPY = "copie"


def journal_dir(destination):
    return os.path.join(destination, STATE_DIR)


def list_journals(destination):
    folder = journal_dir(destination)
    if not os.path.isdir(folder):
        return []
    names = sorted(n for n in os.listdir(folder)
                   if n.startswith("journal-") and n.endswith(".jsonl") and ".annule" not in n)
    return [os.path.join(folder, n) for n in reversed(names)]


def apply_plan(plan, progress=None):
    """Exécute le plan. Renvoie (chemin du journal, nb réussis, [(fichier, erreur)])."""
    opts = plan.options
    mode = MODE_COPY if opts.copy else MODE_MOVE
    todo = plan.to_apply()
    os.makedirs(journal_dir(opts.destination), exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    journal = os.path.join(journal_dir(opts.destination), "journal-%s.jsonl" % stamp)
    done, errors = 0, []
    with open(journal, "a", encoding="utf-8") as log:
        log.write(json.dumps({"debut": stamp, "mode": mode, "source": opts.source,
                              "destination": opts.destination}, ensure_ascii=False) + "\n")
        for n, item in enumerate(todo, 1):
            try:
                if os.path.lexists(item.dest):
                    raise FileExistsError("la destination existe déjà")
                os.makedirs(os.path.dirname(item.dest), exist_ok=True)
                if opts.copy:
                    shutil.copy2(item.src, item.dest)
                else:
                    shutil.move(item.src, item.dest)
                log.write(json.dumps({"src": item.src, "dest": item.dest, "mode": mode,
                                      "action": item.action}, ensure_ascii=False) + "\n")
                log.flush()
                done += 1
            except OSError as exc:
                errors.append((item.src, str(exc)))
            if progress:
                progress("Rangement", n, len(todo))
    return journal, done, errors


def _remove_empty_parents(path, stop):
    folder = os.path.dirname(path)
    while folder and os.path.normcase(folder) != os.path.normcase(stop):
        try:
            os.rmdir(folder)  # n'échoue que si le dossier n'est pas vide : c'est voulu
        except OSError:
            return
        folder = os.path.dirname(folder)


def undo(journal_path, progress=None):
    """Remet chaque fichier là où il était. Renvoie (nb restaurés, [(fichier, erreur)])."""
    with open(journal_path, encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    header, ops = lines[0], [l for l in lines[1:] if "src" in l]
    destination = header.get("destination", "")
    restored, errors = 0, []
    for n, op in enumerate(reversed(ops), 1):
        src, dest = op["src"], op["dest"]
        try:
            if not os.path.lexists(dest):
                raise FileNotFoundError("le fichier rangé a disparu")
            if op["mode"] == MODE_COPY:
                # On ne retire la copie que si elle n'a pas été modifiée depuis.
                if os.path.exists(src) and os.path.getsize(src) != os.path.getsize(dest):
                    raise ValueError("la copie a été modifiée, elle est conservée")
                os.remove(dest)
            else:
                if os.path.lexists(src):
                    raise FileExistsError("un autre fichier occupe déjà l'emplacement d'origine")
                os.makedirs(os.path.dirname(src), exist_ok=True)
                shutil.move(dest, src)
            _remove_empty_parents(dest, destination)
            restored += 1
        except (OSError, ValueError) as exc:
            errors.append((dest, str(exc)))
        if progress:
            progress("Annulation", n, len(ops))
    if not errors:
        os.replace(journal_path, journal_path[:-len(".jsonl")] + ".annule.jsonl")
    return restored, errors
