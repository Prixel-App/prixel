"""Fenêtre de l'application (Tkinter, fourni avec Python)."""

import os
import queue
import threading

from .executor import apply_plan, list_journals, undo
from .planner import ACTION_DUPLICATE, ACTION_IN_PLACE, Options, build_plan
from .report import human_size, summary_lines, write_csv


def run():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Archiviste — rangement automatique")
    root.geometry("1100x720")
    root.minsize(860, 560)

    state = {"plan": None, "busy": False}
    events = queue.Queue()

    source = tk.StringVar()
    destination = tk.StringVar()
    copy = tk.BooleanVar(value=True)  # copier par défaut : le plus prudent
    sessions = tk.BooleanVar(value=True)
    gap = tk.DoubleVar(value=4.0)
    duplicates = tk.BooleanVar(value=True)
    topics = tk.BooleanVar(value=True)
    template = tk.StringVar(value="auto")
    status = tk.StringVar(value="Choisissez le dossier à ranger, puis cliquez sur « Analyser ».")

    # ------------------------------------------------------------ Paramètres
    top = ttk.Frame(root, padding=12)
    top.pack(fill="x")

    def pick(var):
        path = filedialog.askdirectory()
        if path:
            var.set(path)
            if var is source and not destination.get():
                destination.set(path)

    for row, (label, var) in enumerate((("Dossier à ranger", source),
                                        ("Ranger dans", destination))):
        ttk.Label(top, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(top, textvariable=var).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(top, text="Parcourir…", command=lambda v=var: pick(v)).grid(row=row, column=2)
    top.columnconfigure(1, weight=1)

    opts = ttk.Frame(root, padding=(12, 0))
    opts.pack(fill="x")
    ttk.Radiobutton(opts, text="Copier (les originaux restent)", variable=copy, value=True).pack(side="left")
    ttk.Radiobutton(opts, text="Déplacer", variable=copy, value=False).pack(side="left", padx=(8, 20))
    ttk.Checkbutton(opts, text="Photos et vidéos par séance, écart de", variable=sessions).pack(side="left")
    ttk.Spinbox(opts, from_=0.5, to=72, increment=0.5, width=5, textvariable=gap).pack(side="left", padx=4)
    ttk.Label(opts, text="h").pack(side="left")
    opts2 = ttk.Frame(root, padding=(12, 4, 12, 0))
    opts2.pack(fill="x")
    ttk.Checkbutton(opts2, text="Écarter les doublons", variable=duplicates).pack(side="left")
    ttk.Checkbutton(opts2, text="Classer les documents par thème (factures, contrats…)",
                    variable=topics).pack(side="left", padx=20)

    tpl = ttk.Frame(root, padding=(12, 6))
    tpl.pack(fill="x")
    ttk.Label(tpl, text="Modèle de dossiers").pack(side="left")
    ttk.Combobox(tpl, textvariable=template, width=48, values=[
        "auto",
        "{categorie}/{annee}/{seance}",
        "{annee}/{seance}/{categorie}",
        "{categorie}/{annee}/{annee}-{mois}",
        "{categorie}/{appareil}/{annee}",
        "{annee}/{annee}-{mois}/{categorie}",
    ]).pack(side="left", padx=8)
    ttk.Label(tpl, text="auto = Photos/2024/2024-05-12, Documents/Factures/2024",
              foreground="#666").pack(side="left")

    # ---------------------------------------------------------------- Aperçu
    mid = ttk.Frame(root, padding=(12, 6))
    mid.pack(fill="both", expand=True)
    cols = ("action", "categorie", "date", "origine", "taille", "dest")
    tree = ttk.Treeview(mid, columns=cols, show="headings")
    for col, title, width in (("action", "Action", 90), ("categorie", "Catégorie", 110),
                              ("date", "Date", 130), ("origine", "Date lue dans", 90),
                              ("taille", "Taille", 80), ("dest", "Nouvel emplacement", 560)):
        tree.heading(col, text=title)
        tree.column(col, width=width, anchor="w", stretch=(col == "dest"))
    tree.tag_configure("doublon", foreground="#b05a00")
    tree.tag_configure("place", foreground="#888")
    scroll = ttk.Scrollbar(mid, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    summary = tk.Text(root, height=6, relief="flat", background=root.cget("background"))
    summary.pack(fill="x", padx=12)

    # --------------------------------------------------------------- Actions
    bottom = ttk.Frame(root, padding=12)
    bottom.pack(fill="x")
    bar = ttk.Progressbar(bottom, mode="determinate", length=220)
    bar.pack(side="left")
    ttk.Label(bottom, textvariable=status).pack(side="left", padx=12)
    buttons = {}

    def busy(flag):
        state["busy"] = flag
        for name, b in buttons.items():
            enabled = not flag and (name in ("analyse", "undo") or state["plan"] is not None)
            b.state(["!disabled"] if enabled else ["disabled"])

    def progress(stage, done, total):
        events.put(("progress", stage, done, total))

    def background(work, done):
        busy(True)

        def target():
            try:
                events.put(("done", done, work()))
            except Exception as exc:  # affiché à l'utilisateur plutôt qu'ignoré
                events.put(("error", exc))
        threading.Thread(target=target, daemon=True).start()

    def poll():
        try:
            while True:
                ev = events.get_nowait()
                if ev[0] == "progress":
                    _, stage, done, total = ev
                    if total:
                        bar.configure(mode="determinate", maximum=total, value=done)
                        status.set("%s : %d / %d" % (stage, done, total))
                    else:
                        bar.configure(mode="indeterminate")
                        bar.step(5)
                        status.set("%s : %d fichiers…" % (stage, done))
                elif ev[0] == "done":
                    busy(False)
                    ev[1](ev[2])
                else:
                    busy(False)
                    status.set("Erreur.")
                    messagebox.showerror("Archiviste", str(ev[1]))
        except queue.Empty:
            pass
        root.after(80, poll)

    def show_plan(plan):
        state["plan"] = plan
        busy(False)
        tree.delete(*tree.get_children())
        for item in plan.items[:20000]:
            tag = ("doublon",) if item.action == ACTION_DUPLICATE else \
                  ("place",) if item.action == ACTION_IN_PLACE else ()
            tree.insert("", "end", tags=tag, values=(
                item.action, item.category, item.meta.date.strftime("%Y-%m-%d %H:%M"),
                item.meta.source, human_size(item.size),
                os.path.relpath(item.dest, plan.options.destination)))
        summary.delete("1.0", "end")
        summary.insert("1.0", "\n".join(summary_lines(plan)))
        status.set("Aperçu prêt : rien n'a encore été modifié.")

    def analyse():
        if not source.get():
            messagebox.showinfo("Archiviste", "Choisissez d'abord le dossier à ranger.")
            return
        o = Options(source.get(), destination.get() or source.get(), copy=copy.get(),
                    sessions=sessions.get(), session_gap_hours=gap.get(),
                    duplicates=duplicates.get(), topics=topics.get(), template=template.get())
        state["plan"] = None
        background(lambda: build_plan(o, progress), show_plan)

    def apply():
        plan = state["plan"]
        n = len(plan.to_apply())
        if not n:
            messagebox.showinfo("Archiviste", "Tout est déjà rangé.")
            return
        verb = "copiés" if copy.get() else "déplacés"
        if not messagebox.askyesno("Archiviste", "%d fichiers vont être %s vers\n%s\n\n"
                                   "Aucun fichier ne sera supprimé ni écrasé, et l'opération "
                                   "pourra être annulée. Continuer ?"
                                   % (n, verb, plan.options.destination)):
            return
        plan.options.copy = copy.get()

        def finished(result):
            _, done, errors = result
            state["plan"] = None
            busy(False)
            msg = "%d fichiers rangés." % done
            if errors:
                msg += "\n\n%d erreurs :\n" % len(errors) + "\n".join(
                    "%s — %s" % e for e in errors[:15])
            status.set(msg.splitlines()[0])
            messagebox.showinfo("Archiviste", msg)
        background(lambda: apply_plan(plan, progress), finished)

    def cancel_last():
        dest = destination.get() or source.get()
        journals = list_journals(dest) if dest else []
        if not journals:
            messagebox.showinfo("Archiviste", "Aucun rangement à annuler dans ce dossier.")
            return
        if not messagebox.askyesno("Archiviste", "Annuler le dernier rangement ?\n\n"
                                   "Les fichiers déplacés retournent à leur place d'origine, "
                                   "les copies sont retirées."):
            return

        def finished(result):
            restored, errors = result
            msg = "%d fichiers remis à leur place." % restored
            if errors:
                msg += "\n\n%d n'ont pas pu l'être :\n" % len(errors) + "\n".join(
                    "%s — %s" % e for e in errors[:15])
            status.set(msg.splitlines()[0])
            messagebox.showinfo("Archiviste", msg)
        background(lambda: undo(journals[0], progress), finished)

    def export():
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            initialfile="plan-de-rangement.csv")
        if path:
            write_csv(state["plan"], path)
            status.set("Plan exporté : %s" % path)

    buttons["undo"] = ttk.Button(bottom, text="Annuler le dernier rangement", command=cancel_last)
    buttons["export"] = ttk.Button(bottom, text="Exporter (CSV)", command=export)
    buttons["apply"] = ttk.Button(bottom, text="Ranger", command=apply)
    buttons["analyse"] = ttk.Button(bottom, text="Analyser", command=analyse)
    for name in ("apply", "export", "analyse", "undo"):
        buttons[name].pack(side="right", padx=4)
    busy(False)

    root.after(80, poll)
    root.mainloop()
    return 0
