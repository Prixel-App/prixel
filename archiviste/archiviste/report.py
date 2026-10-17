"""Présentation du plan : résumé lisible et export CSV."""

import csv
import os

from .planner import ACTION_IN_PLACE


def human_size(n):
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024 or unit == "To":
            return ("%d %s" % (n, unit)) if unit == "o" else ("%.1f %s" % (n, unit)).replace(".", ",")
        n /= 1024.0


def summary_lines(plan):
    lines = []
    total = sum(i.size for i in plan.items)
    lines.append("%d fichiers analysés (%s)" % (len(plan.items), human_size(total)))
    for cat, (count, size) in sorted(plan.summary().items(), key=lambda kv: -kv[1][1]):
        lines.append("  %-16s %6d fichiers  %10s" % (cat, count, human_size(size)))
    in_place = sum(1 for i in plan.items if i.action == ACTION_IN_PLACE)
    if in_place:
        lines.append("%d fichiers sont déjà à leur place." % in_place)
    if plan.skipped:
        lines.append("%d éléments laissés de côté (paquets, liens, illisibles)." % len(plan.skipped))
    return lines


def tree_lines(plan, max_folders=40):
    """Aperçu de l'arborescence qui sera créée, avec le nombre de fichiers par dossier."""
    counts = {}
    for item in plan.to_apply():
        folder = os.path.relpath(os.path.dirname(item.dest), plan.options.destination)
        counts[folder] = counts.get(folder, 0) + 1
    lines = []
    for folder in sorted(counts)[:max_folders]:
        lines.append("  %s%s  (%d)" % (folder.replace(os.sep, "/"), "/", counts[folder]))
    if len(counts) > max_folders:
        lines.append("  … et %d autres dossiers" % (len(counts) - max_folders))
    return lines


def write_csv(plan, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Action", "Catégorie", "Thème", "Date", "Source de la date", "Appareil",
                    "Taille", "Fichier d'origine", "Nouvel emplacement", "Doublon de"])
        for i in plan.items:
            w.writerow([i.action, i.category, i.topic or "", i.meta.date.strftime("%Y-%m-%d %H:%M"),
                        i.meta.source, i.meta.camera or "", i.size, i.src, i.dest,
                        i.duplicate_of or ""])
