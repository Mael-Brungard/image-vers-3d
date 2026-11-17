"""
image_checks.py - Conseils sur l'image de départ (sans Qt, rapide, jamais bloquant).

Avec tous les modèles image -> 3D, la qualité de l'image d'entrée pèse plus que n'importe quel réglage. Ces contrôles
repèrent les trois défauts les plus fréquents et les plus sûrs à détecter :

  - image trop petite (le modèle manque de détails) ;
  - image floue (aucun contour net) ;
  - objet coupé par le bord de l'image (le modèle invente le reste).

Ce sont des conseils : le logiciel ne refuse jamais une image. Les seuils sont volontairement prudents, pour ne pas
afficher de fausse alerte (une illustration à fond uni a peu de texture mais des contours nets, par exemple).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

MIN_SIDE = 512  # en dessous, les détails manquent
BLUR_RATIO = 0.07  # contour le plus net / contraste de l'image, par pixel à 512 px : en dessous, image floue
ANALYSIS_SIDE = 512  # les mesures se font sur une copie réduite : rapide même pour une image de 4000 px
CORNER_SHARE = 0.08  # taille des coins (part du petit côté) qui servent à mesurer le fond
CORNER_UNIFORM = 0.9  # part des pixels des coins proches de la couleur de fond pour dire « fond uni »
CORNER_DISTANCE = 16  # écart de couleur (0-255) toléré dans un fond uni
FOREGROUND_DISTANCE = 32  # écart de couleur (0-255) à partir duquel un pixel n'est plus du fond
TOUCH_SHARE = 0.08  # part d'un côté occupée par l'objet pour dire qu'il touche ce côté

TIP_SMALL = "Image petite ({w} × {h}) : le modèle manquera de détails. Vise au moins 1024 px de côté."
TIP_BLURRY = "Image floue : les contours ne sont pas nets, le modèle sera approximatif. Une image nette donne un bien meilleur résultat."
TIP_CUT = "L'objet semble coupé par le bord de l'image : cadre-le en entier, avec une marge tout autour."


def _reduced(image: Image.Image, side: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((side, side), Image.Resampling.BILINEAR)
    return copy


def sharpness_ratio(image: Image.Image) -> float:
    """Netteté relative : contour le plus net (99,9e centile du gradient de la luminosité) divisé par le contraste de l'image
    (écart entre le 0,5e et le 99,5e centile), à 512 px de côté maximum. Une image nette a des transitions d'un ou deux
    pixels (rapport de 0,2 à 1) ; une image floue étale le même contraste sur des dizaines de pixels (moins de 0,07)."""
    grey = np.asarray(_reduced(image.convert("L"), ANALYSIS_SIDE), dtype=np.float32)
    if min(grey.shape) < 3:
        return 0.0
    gy, gx = np.gradient(grey)
    edge = float(np.percentile(np.hypot(gx, gy), 99.9))
    low, high = np.percentile(grey, [0.5, 99.5])
    return edge / max(float(high - low), 16.0)


def _side_shares(mask: np.ndarray) -> list[float]:
    """Part de chaque côté (haut, bas, gauche, droite) recouverte par l'objet, sur une bande de quelques pixels."""
    band = max(2, round(min(mask.shape) * 0.02))
    return [float(mask[:band].any(axis=0).mean()), float(mask[-band:].any(axis=0).mean()),
            float(mask[:, :band].any(axis=1).mean()), float(mask[:, -band:].any(axis=1).mean())]


def touches_border(image: Image.Image) -> bool:
    """L'objet touche le bord de l'image. Image détourée : d'après la transparence. Sinon : seulement si le fond est uni
    (sans quoi on ne sait pas distinguer l'objet du décor, et on ne dit rien)."""
    small = _reduced(image, ANALYSIS_SIDE // 2)
    if small.mode in ("RGBA", "LA"):
        alpha = np.asarray(small.getchannel("A"))
        if (alpha < 128).mean() >= 0.005:  # vraie transparence
            return max(_side_shares(alpha >= 128)) > TOUCH_SHARE
    rgb = np.asarray(small.convert("RGB"), dtype=np.int16)
    size = max(3, round(min(rgb.shape[:2]) * CORNER_SHARE))
    corners = np.concatenate([rgb[:size, :size].reshape(-1, 3), rgb[:size, -size:].reshape(-1, 3),
                              rgb[-size:, :size].reshape(-1, 3), rgb[-size:, -size:].reshape(-1, 3)])
    background = np.median(corners, axis=0)  # un objet recouvre rarement les quatre coins : ils donnent la couleur du fond
    if (np.abs(corners - background).max(axis=1) < CORNER_DISTANCE).mean() < CORNER_UNIFORM:
        return False  # fond non uni (décor, dégradé, texture) : impossible de dire où finit l'objet
    foreground = np.abs(rgb - background).max(axis=2) > FOREGROUND_DISTANCE
    if foreground.mean() > 0.85 or foreground.mean() < 0.005:  # tout est « objet » ou rien ne l'est : mesure peu fiable
        return False
    return max(_side_shares(foreground)) > TOUCH_SHARE


def check_image(image: Image.Image) -> list[str]:
    """Conseils (phrases prêtes à afficher) ; liste vide si l'image n'appelle aucune remarque."""
    tips: list[str] = []
    width, height = image.size
    if min(width, height) < MIN_SIDE:
        tips.append(TIP_SMALL.format(w=width, h=height))
    try:
        if sharpness_ratio(image) < BLUR_RATIO:
            tips.append(TIP_BLURRY)
        if touches_border(image):
            tips.append(TIP_CUT)
    except Exception:  # noqa: BLE001 - un conseil raté ne doit jamais empêcher de charger l'image
        pass
    return tips


# Prompt à donner à un générateur d'images (ChatGPT, etc.) pour obtenir une image de départ idéale.
# Le même texte figure dans docs/IMAGE_DE_DEPART.md (un test vérifie qu'ils restent identiques).
IMAGE_PROMPT = """Crée une image de [DÉCRIS ICI TON PERSONNAGE OU TON OBJET], destinée à être transformée en modèle 3D.

Cadrage
- Un seul sujet, entier et centré, avec au moins 10 % de marge tout autour : rien ne touche le bord de l'image (ni la tête, ni les pieds, ni un objet tenu).
- Vue de trois quarts de face, caméra à hauteur du sujet, légèrement en plongée (environ 15°). Pas de vue extrême, pas de perspective déformante.
- Image carrée, la plus grande résolution possible, très nette.

Pose (si c'est un personnage ou un animal)
- Pose calme et lisible : bras écartés du corps, jambes légèrement écartées, tous les membres bien visibles et non croisés.
- Mains, accessoires et cheveux épais et simples : rien de filaire ou de très fin (épée fine, fils, plumes isolées).

Lumière et couleurs
- Éclairage de studio doux et uniforme, sans ombre portée, sans reflet brillant fort, sans contre-jour.
- Couleurs fidèles et matériaux lisibles (tissu, métal, plastique), sans filtre ni effet.

Fond
- Fond uni, sans sol, sans décor, sans ombre au sol. Couleur : gris clair (#E8E8E8) ; si le sujet est gris, blanc ou argenté, utilise un vert vif uni (#00B140) à la place.

Style : rendu de figurine ou d'objet 3D propre, détails nets et bien définis.
Interdit : texte, logo, filigrane, cadre, plusieurs sujets, flou ou profondeur de champ."""
