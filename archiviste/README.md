# Archiviste

Classe automatiquement les fichiers en vrac d'un disque : photos, rushes, RAW,
sons, documents, fichiers de création… Pensé d'abord pour les photographes,
réalisateurs et auteurs, mais utile pour n'importe quel disque en désordre.

Aucune installation de bibliothèque : il suffit de Python 3.8 ou plus récent
(déjà présent sur macOS et Linux ; sous Windows, voir [python.org](https://www.python.org/downloads/)).

## Ce qu'il fait

- **Reconnaît le type** de chaque fichier (≈ 200 extensions, dont tous les RAW
  courants : CR2, CR3, NEF, ARW, RAF, DNG, ORF, RW2…).
- **Retrouve la vraie date** de prise de vue, et non celle de la dernière copie :
  EXIF des photos et des RAW, métadonnées des vidéos MP4/MOV, date écrite dans le
  nom (`IMG_20240512_143000.jpg`, `IMG-20240512-WA0001.jpg`…), puis en dernier
  recours la date du fichier.
- **Regroupe photos et vidéos par séance** : tant que les prises de vue se suivent
  à moins de 4 heures d'écart (réglable), elles vont dans le même dossier.
  Deux séances le même jour donnent `2024-05-12` et `2024-05-12 (2)`.
- **Range les documents par thème** d'après leur nom : Factures, Devis, Contrats,
  Autorisations (droit à l'image), Banque, Impôts, Administratif, Scénarios,
  Écrits, Présentations, CV.
- **Écarte les doublons** : les fichiers au contenu strictement identique (même
  sous un autre nom) vont dans `_Doublons/`. Ils ne sont jamais supprimés : c'est
  vous qui décidez ensuite.
- **Lit l'appareil** utilisé (pour un classement du type `{categorie}/{appareil}/{annee}`).

Résultat par défaut :

```
Photos/2024/2024-05-12/
Photos/2024/2024-05-12 (2)/
Photos RAW/2024/2024-05-12/
Vidéos/2024/2024-05-12/
Documents/Factures/2024/
Documents/Scénarios/2023/
Audio/2024/2024-03/
Création/2024/2024-06/
Autres/
_Doublons/…
```

## Sécurité

- **Aperçu d'abord** : rien n'est touché tant que vous n'avez pas validé.
- **Rien n'est jamais supprimé ni écrasé** : en cas de nom déjà pris, le fichier
  devient `nom (2).jpg`.
- **Tout est annulable** : chaque rangement est consigné au fur et à mesure dans
  `.archiviste/` (dans le dossier d'arrivée). « Annuler le dernier rangement »
  remet chaque fichier exactement où il était, même après une coupure de courant
  en plein travail.
- **Mode copie** proposé par défaut dans la fenêtre : les originaux restent en place.
- Ne touche pas aux bibliothèques et paquets (Photos `.photoslibrary`, Final Cut
  `.fcpbundle`, données Lightroom `.lrdata`, applications…), ni aux fichiers
  système (`.DS_Store`, `Thumbs.db`, corbeilles).
- Relancé sur un dossier déjà rangé, il ne déplace plus rien.

> ⚠️ **Lightroom, Capture One, Premiere, DaVinci…** retrouvent les fichiers par
> leur emplacement. Déplacer des médias déjà importés dans un catalogue ou un
> projet casse les liens. Pour ces dossiers, utilisez le **mode copie**, ou
> rangez avant d'importer.

## Utilisation

### Avec l'interface

Double-cliquez sur `Archiviste.command` (macOS) ou `Archiviste.bat` (Windows),
ou lancez :

```
python3 -m archiviste
```

L'interface s'ouvre dans sa propre fenêtre (Chrome ou Edge en mode application,
sinon dans votre navigateur). Tout se passe sur votre ordinateur : rien n'est
envoyé sur Internet.

1. **Préparer** : choisissez le disque à ranger et la destination, la méthode
   (copie ou déplacement), l'écart entre séances et l'organisation des dossiers.
2. **Vérifier** : chiffres clés (fichiers, volume, séances, doublons, part des dates
   sûres), répartition par catégorie, arborescence à venir avec les vignettes de
   chaque séance (aperçus des RAW compris), liste complète filtrable, doublons
   côte à côte avec leur original.
3. **Ranger** : confirmez. Le bouton **Historique** permet d'annuler n'importe quel
   rangement passé.

Fermer la fenêtre arrête Archiviste au bout de quelques minutes. L'ancienne fenêtre
simple reste disponible avec `python3 -m archiviste --classique`.

### En ligne de commande

```
# Aperçu (ne modifie rien), avec export du plan détaillé en CSV
python3 -m archiviste "/Volumes/Disque/Vrac" "/Volumes/Archives" --csv plan.csv

# Ranger réellement, en copiant
python3 -m archiviste "/Volumes/Disque/Vrac" "/Volumes/Archives" --copier --appliquer

# Ranger un dossier sur lui-même, en déplaçant
python3 -m archiviste "D:\Photos en vrac" --appliquer

# Annuler le dernier rangement
python3 -m archiviste annuler "/Volumes/Archives"
```

Options utiles : `--ecart 2` (séances séparées par 2 h), `--sans-seances`
(un dossier par jour), `--sans-doublons`, `--sans-themes`, `--caches`
(inclure les fichiers cachés).

### Modèle de dossiers personnalisé

`--modele` (ou le champ « Modèle de dossiers » de la fenêtre) accepte les variables
`{categorie}`, `{theme}`, `{annee}`, `{mois}`, `{jour}`, `{seance}`, `{appareil}`,
`{extension}`. Exemples :

| Modèle | Résultat |
|---|---|
| `{annee}/{seance}/{categorie}` | `2024/2024-05-12/Photos RAW/` — JPEG, RAW et vidéos d'une même séance côte à côte |
| `{categorie}/{appareil}/{annee}` | `Photos/FUJIFILM X-T5/2024/` |
| `{annee}/{annee}-{mois}/{categorie}` | `2024/2024-05/Documents/` |

## Personnaliser

- Catégories et extensions : `archiviste/categories.py` (`CATEGORIES`).
- Thèmes des documents et mots-clés : même fichier (`DOCUMENT_TOPICS`).

## Tests

```
python3 -m unittest discover -s tests
```
