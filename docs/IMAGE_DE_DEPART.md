# Obtenir le meilleur résultat : l'image de départ et les réglages

Avec tous les modèles image vers 3D, **l'image de départ compte plus que n'importe quel réglage**. Le modèle voit une seule vue
et invente le reste (le dos, les côtés, ce qui est caché) : plus l'image est claire, plus ce qu'il invente est juste.
Ce guide dit quoi faire, dans l'ordre d'efficacité. Aucune de ces recommandations n'a été mesurée sur ta carte ; elles viennent
de la documentation des modèles et du bon sens de la 3D. Vérifie-les avec tes propres images.

## 1. Une bonne image (le levier numéro un)

Dans le logiciel, **Réglages (⋯) → « Copier le prompt ChatGPT »** copie le texte ci-dessous. Colle-le dans ChatGPT
(ou un autre générateur d'images) et remplace les crochets par ta description.

```text
Crée une image de [DÉCRIS ICI TON PERSONNAGE OU TON OBJET], destinée à être transformée en modèle 3D.

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
Interdit : texte, logo, filigrane, cadre, plusieurs sujets, flou ou profondeur de champ.
```

Pourquoi chaque consigne :

| Consigne | Raison |
|---|---|
| Sujet entier, marge de 10 % | un objet coupé par le bord oblige le modèle à inventer la partie manquante |
| Trois quarts de face, légèrement en plongée | on voit à la fois le devant, un côté et le dessus : c'est la vue qui renseigne le mieux sur le volume |
| Bras et jambes écartés, membres non croisés | des membres collés au corps ou cachés fusionnent en un bloc |
| Rien de filaire ou de très fin | les détails plus fins que la grille du modèle (épée, fils, plumes) disparaissent ou fusionnent |
| Lumière douce, sans ombre portée ni reflet fort | une ombre ou un reflet est pris pour de la matière : le modèle en fait un creux ou une bosse |
| Fond uni, différent du sujet | le détourage (BiRefNet) est alors presque parfait ; un fond de même teinte « mange » le sujet |

Génère **trois ou quatre images** et garde la plus nette et la plus propre : cinq minutes à ce stade évitent d'attendre des
calculs sur une mauvaise image. Le logiciel te prévient (« Conseil : … ») quand l'image est petite (moins de 512 px de côté),
floue, ou que l'objet touche le bord ; il ne refuse jamais une image.

Pour imprimer en 3D : choisis des formes épaisses (pas d'épée fine, pas de cheveux filaires) et un socle ; les finitions fines se
reprennent ensuite dans Blender.

## 2. Les réglages, du plus utile au moins utile

1. **Qualité « Détaillé » (1024)** : le grand saut par rapport à « Rapide » (512).
2. **Variantes à comparer (2 à 4)** : l'IA invente ce que l'image ne montre pas, et chaque numéro de variante invente autrement.
   Compare avec le sélecteur « Variante » sous le modèle et enregistre la meilleure ; un nom de fichier `_v2` indique la variante.
   C'est souvent plus efficace que de monter la qualité. Compte plusieurs minutes par variante.
3. **Précision « Haute » (poids q8, 10 Go de plus)** : texture plus propre. À essayer quand « Détaillé » passe sans message de
   repli. Elle demande plus de mémoire vidéo ; si la carte manque de place, repasse en Standard.
4. **Texture très fine (expérimental)** : atlas de 4096 px et décodage PBR en 1024. Plus de détails dans les couleurs, mais plus de
   mémoire et de temps ; si la carte manque de place, le logiciel refait avec la texture standard et te le dit.
5. **Qualité « Maximum »** (24 étapes au lieu de 12) : gain faible, temps doublé. À garder pour la version finale.
6. **Qualité « Ultra » (1536, expérimental)** : la géométrie la plus fine, mais jamais vue sur une carte de 12 Go. Si la mémoire
   manque, le calcul est refait en 1024 puis en 512 (c'est indiqué dans la ligne d'état) ; compte alors beaucoup de temps perdu.

## 3. Méthode conseillée

1. Image prête (section 1).
2. Un essai en **Rapide** (1 à 2 minutes) pour vérifier la forme et le détourage (bouton « Détourée » pour voir le détourage).
3. Calcul en **Détaillé avec 3 variantes** ; choisis la meilleure.
4. Seulement ensuite, essaie sur cette image-là : Précision Haute, Texture très fine, Maximum.
5. Compare dans Blender le même angle de chaque essai pour savoir ce qui t'apporte vraiment quelque chose.

## 4. Si le résultat déçoit

| Symptôme | Cause probable | Que faire |
|---|---|---|
| Forme floue, détails mous | image petite ou floue, ou qualité Rapide | image plus nette, qualité Détaillé |
| Partie manquante ou fusionnée | membre caché, croisé ou trop fin | autre pose, formes plus épaisses |
| Objet couché | orientation de la sortie | boutons « Redresser » et « Pivoter » |
| Dos faux | le modèle n'a vu que le devant | prompt trois quarts, plusieurs variantes |
| Texture granuleuse | poids Standard | précision Haute (si la mémoire suffit) |
| Trous ou bosses sur les reflets | reflets dans l'image | éclairage doux, sans reflet |
| Sujet « mangé » par le détourage | fond de la même teinte que le sujet | fond d'une autre couleur (vert vif) |
