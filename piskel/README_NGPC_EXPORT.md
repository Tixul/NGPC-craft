# Piskel NGPC Export (Custom)

Ce document décrit l’export NGPC ajouté dans ce dépôt Piskel, et les fichiers modifiés.

## Où trouver l’export

Dans l’UI Piskel :
`Export` → `Others` → **Export as C File**

## Caractéristiques de l’export NGPC

Le format est pensé pour NGPC (T6W28 / tiled 8x8) :
- **Tiles 8x8** uniquement (largeur/hauteur doivent être multiples de 8).
- **2bpp** (4 couleurs indexées par tile : 0..3).
- **Index 0 = transparent**.
- **Palette en RGB444** (packed `0x0BGR`).
- **Export “layered”** : l’image est découpée en **couches** par tile.
  - Chaque couche peut contenir **jusqu’à 3 couleurs opaques** + transparent.
  - Les couches sont **superposées** pour reconstruire l’image.

## Paramètres ajoutés (UI)

Dans la section “Export as C File” :
- **NGPC profile**
  - `Sprite (default)` : valeurs adaptées aux sprites (ex: 3 layers / 16 palettes).
  - `Background` : valeurs plus larges (ex: 6 layers / 32 palettes).
- **Max layers**
  - Nombre de couches max par tile.
  - 1 layer = 3 couleurs max par tile (opaque) + transparent.
  - 3 layers = 9 couleurs max par tile (opaque) + transparent.
  - 6 layers = 18 couleurs max par tile (opaque) + transparent.
- **Max palettes (per layer)**
  - Nombre de palettes max par couche.
  - Une palette = 4 entrées RGB444 (index 0 = transparent).

## Format de sortie (C)

Le C généré contient :
- Constantes de taille (frame count, width/height, tiles X/Y, etc.)
- **Palettes par layer** (`pal_rgb444`)
- **Palette ID par tile** (`tile_pal`)
- **Données tiles** (`tiles`)
- **Positions tiles** (coordonnées 8x8, utile pour placer rapidement)

## Limites importantes

- Si une tile utilise **trop de couleurs**, l’export échoue.
- Si le nombre de **palettes distinctes** par layer dépasse la limite, l’export échoue.
- Les couleurs **très proches** (ex: variations d’un même jaune) comptent comme des couleurs **différentes**.

## Fichiers touchés

UI :
- `src/templates/settings/export/misc.html`

Logique export :
- `src/js/controller/settings/exportimage/MiscExportController.js`

(Les fichiers `dest/` ont été régénérés automatiquement par le build et contiennent les mêmes changements packagés.)

## Récapitulatif clair (tous les fichiers touchés)

Modifiés :
- `src/templates/settings/export/misc.html`
- `src/js/controller/settings/exportimage/MiscExportController.js`

Ajoutés :
- `README_NGPC_EXPORT.md`

Packagés (si tu utilises `dest/` directement) :
- `dest/prod/index.html`
- `dest/prod/piskelapp-partials/main-partial.html`
- `dest/prod/piskelapp-partials/piskel-web-partial.html`
- `dest/prod/piskelapp-partials/piskel-web-partial-kids.html`
- `dest/prod/js/piskel-packaged-2026-02-03-07-46.js`
- `dest/prod/js/piskel-packaged-min-2026-02-03-07-46.js`

## Procédure d'installation (recommandée)

Cette modif est prévue pour être appliquée **sur un dépôt Piskel existant**.

1) Cloner Piskel officiel  
2) Copier les fichiers modifiés par-dessus :
   - `src/templates/settings/export/misc.html`
   - `src/js/controller/settings/exportimage/MiscExportController.js`
3) Ajouter `README_NGPC_EXPORT.md` à la racine du repo (optionnel)
4) Lancer Piskel (version web locale) :
   - Ouvrir `dest/prod/index.html` dans un navigateur
   - Ou rebuild via `grunt` si besoin

## Version Piskel utilisée

Basée sur `piskel` **v0.15.2-SNAPSHOT** (voir `package.json`).

## Conseils pratiques

Pour des fonds NGPC :
- Utiliser une **palette stricte** (éviter les variations proches).
- Garder **≤ 4 couleurs par tile** si tu veux un fond “1 layer”.
- Si besoin, monter `Max layers` et `Max palettes` dans l’export.
