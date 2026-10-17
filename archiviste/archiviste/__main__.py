"""Ligne de commande.

  python -m archiviste                         ouvre la fenêtre
  python -m archiviste SOURCE DEST             aperçu (rien n'est modifié)
  python -m archiviste SOURCE DEST --appliquer range pour de vrai
  python -m archiviste annuler DEST            annule le dernier rangement
"""

import argparse
import sys

from . import __version__
from .executor import apply_plan, list_journals, undo
from .planner import PLACEHOLDERS, Options, build_plan
from .report import summary_lines, tree_lines, write_csv


def _progress(stage, done, total):
    if total:
        sys.stderr.write("\r%s : %d / %d   " % (stage, done, total))
        if done >= total:
            sys.stderr.write("\n")
    else:
        sys.stderr.write("\r%s : %d…   " % (stage, done))
    sys.stderr.flush()


def _undo(argv):
    p = argparse.ArgumentParser(prog="archiviste annuler",
                                description="Annule le dernier rangement fait vers DEST.")
    p.add_argument("destination")
    p.add_argument("--journal", help="journal précis à annuler (par défaut : le plus récent)")
    a = p.parse_args(argv)
    journal = a.journal or next(iter(list_journals(a.destination)), None)
    if not journal:
        print("Aucun rangement à annuler dans ce dossier.")
        return 1
    restored, errors = undo(journal, _progress)
    print("%d fichiers remis à leur place." % restored)
    for path, err in errors:
        print("  ! %s — %s" % (path, err))
    return 1 if errors else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .gui import run
        return run()
    if argv[0] == "annuler":
        return _undo(argv[1:])

    p = argparse.ArgumentParser(
        prog="archiviste",
        description="Classe automatiquement des fichiers en vrac. Sans --appliquer, "
                    "affiche seulement ce qui serait fait.",
    )
    p.add_argument("source", help="dossier à ranger")
    p.add_argument("destination", nargs="?", help="dossier d'arrivée (par défaut : le même)")
    p.add_argument("--appliquer", action="store_true", help="effectue réellement le rangement")
    p.add_argument("--copier", action="store_true", help="copie au lieu de déplacer")
    p.add_argument("--sans-seances", action="store_true",
                   help="classe photos et vidéos par jour plutôt que par séance")
    p.add_argument("--ecart", type=float, default=4.0, metavar="HEURES",
                   help="durée sans prise de vue qui sépare deux séances (défaut : 4)")
    p.add_argument("--sans-doublons", action="store_true", help="ne cherche pas les doublons")
    p.add_argument("--sans-themes", action="store_true",
                   help="ne sous-classe pas les documents (factures, contrats…)")
    p.add_argument("--modele", default="auto",
                   help="modèle de dossiers, ex. \"{categorie}/{annee}/{seance}\". "
                        "Variables : " + ", ".join("{%s}" % k for k in PLACEHOLDERS))
    p.add_argument("--caches", action="store_true", help="inclut les fichiers cachés")
    p.add_argument("--csv", metavar="FICHIER", help="exporte le plan détaillé en CSV")
    p.add_argument("--version", action="version", version="Archiviste " + __version__)
    a = p.parse_args(argv)

    opts = Options(
        a.source, a.destination or a.source, copy=a.copier, sessions=not a.sans_seances,
        session_gap_hours=a.ecart, duplicates=not a.sans_doublons, topics=not a.sans_themes,
        template=a.modele, include_hidden=a.caches,
    )
    plan = build_plan(opts, _progress)
    print("\n".join(summary_lines(plan)))
    print("\nDossiers qui seront créés dans %s :" % opts.destination)
    print("\n".join(tree_lines(plan)) or "  (aucun : tout est déjà rangé)")
    if a.csv:
        write_csv(plan, a.csv)
        print("\nPlan détaillé écrit dans %s" % a.csv)
    if not a.appliquer:
        print("\nAperçu seulement. Relancez avec --appliquer pour ranger.")
        return 0
    journal, done, errors = apply_plan(plan, _progress)
    print("\n%d fichiers rangés. Pour annuler : python -m archiviste annuler \"%s\""
          % (done, opts.destination))
    for path, err in errors:
        print("  ! %s — %s" % (path, err))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
