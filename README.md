# Banc d'essai « Terre du Milieu »

Ce n'est pas l'application. C'est un instrument de mesure, destiné à répondre à
deux questions avant l'écriture du cahier des charges v3.0 :

1. **Les invités savent-ils répondre seuls aux six questions ?**
2. **Les portraits produits sont-ils devinables ?**

Ce qui est représentatif de la version réelle : le parcours, le questionnaire, le
prompt, l'assignation des lieux, le plafond de trois réécritures, la génération
hors du fil de la requête.

Ce qui n'y est pas : mot de passe de table, photo, quotas, file de tâches
persistée, SQLAlchemy, sauvegardes, phases de soirée. Inutile pour le test.

---

## Déploiement sur Railway

1. Nouveau dépôt GitHub, ce dossier à la racine, `git push`.
2. Railway → *New Project* → *Deploy from GitHub repo*. Le `Dockerfile` est
   détecté tout seul.
3. Onglet **Variables** :

   | Variable | Valeur |
   |---|---|
   | `ANTHROPIC_API_KEY` | la clé de la console Anthropic |
   | `MOT_DE_PASSE_ADMIN` | un mot de passe long |
   | `MODELE_IA` | `claude-sonnet-5` |
   | `PRENOM_MARIEE` | `Delphine` |
   | `PRENOM_MARIE` | `Jérémy` |
   | `EXIGER_VOLUME` | `1` |

   Les prénoms des mariés apparaissent dans les libellés du questionnaire et
   sont transmis au modèle **pour comprendre les réponses**, jamais pour être
   écrits : ils figurent aussi dans la liste des noms interdits en sortie.

4. Onglet **Settings** → *Generate Domain*.
5. **Volume persistant : indispensable.** Onglet *Volumes* → *New Volume*,
   point de montage `/data`. Sans lui, la base vit dans le conteneur et
   **chaque redéploiement efface tout** — y compris un simple ajout de
   variable. Pose `EXIGER_VOLUME=1` : le service refusera alors de démarrer
   sans volume, au lieu de perdre les données en silence.

Réplique unique, comme l'application réelle : SQLite n'accepte pas deux
conteneurs sur le même fichier.

En local : `pip install -r requirements.txt` puis
`uvicorn main:app --reload`, avec les variables d'environnement exportées.

---

## Les pages

| Adresse | À qui |
|---|---|
| `/` | l'invité — questionnaire, portrait, six questions bonus |
| `/deviner` | **toi**, avec quelqu'un qui connaît les participants |
| `/tableau` | latences, jetons, échecs, fuites de noms, répartition des lieux |
| `/tableau/export.json` | tout, pour archiver la session de test |

`/deviner` et `/tableau` demandent le mot de passe administrateur par
authentification HTTP. `/` est ouvert : aucun mot de passe de table dans ce
banc d'essai.

---

## Protocole de test

0. **Le parcours** : six questions, puis un choix — *Créer mon personnage* ou
   *Six questions de plus*. Ceux qui créent tout de suite se voient reproposer
   les six autres après lecture du portrait ; ceux qui les ont déjà données ne
   les revoient pas. Les questions complémentaires sont facultatives une par
   une : on peut en sauter.

1. **Ne montre l'écran à personne avant.** Envoie le lien à huit personnes que
   tu connais bien, sans explication, chacune sur son propre téléphone. C'est
   ton `EX-PLA-01` appliqué trois semaines en avance.
2. **Regarde par-dessus l'épaule d'au moins deux d'entre elles.** Où hésitent-
   elles ? Quelle question fait ressortir un « je réponds quoi, là ? » Ce
   moment vaut plus que tout ce que le tableau de bord affiche.
3. **Note qui prend les six questions complémentaires, et à quel moment** —
   avant la création du personnage, ou après l'avoir lu. Si personne ne les
   prend, le second étage ne sert à rien et le roman s'écrira sur six réponses.
   Si tous les preneurs le font *avant*, la seconde proposition peut disparaître.
4. **Ouvre `/deviner` avec quelqu'un qui connaît les huit.** Les boutons
   *Deviné* / *Raté* comptent pour toi.
5. **Lis le tableau** : attente maximale, échecs, fuites de noms.

### Interprétation

| Constat | Ce qu'il faut corriger |
|---|---|
| moins de trois quarts de réussite | **les questions** — pas le prompt |
| des portraits qui se ressemblent tous | l'IA abstrait : durcir la règle des trois ancres |
| des abandons en cours de questionnaire | trop de saisie libre, ou question mal comprise |
| attente au-delà de vingt secondes | essayer Haiku 4.5, ou accepter et le dire à l'écran |
| des fuites de noms | renforcer la règle 3 du contrat |

Les questions, les lieux et le contrat de style sont **tous dans
`questions.yaml`**. Corriger et redéployer ne touche pas une ligne de code —
c'est exactement ce qui te permettra de continuer à les affiner après
l'écriture de la v3.0.

---

## Limites connues

- **Le contrôle des noms signale, il ne corrige pas.** Un remplacement
  automatique produirait des phrases cassées. À la relecture, tu tranches.
- **Faux positifs possibles** sur les prénoms qui sont aussi des mots courants
  (Pierre, Rose, Olivier). C'est un signal pour un humain, pas un verdict.
- **La génération n'a pas été essayée contre l'API** au moment de l'écriture de
  ce dossier : pas de clé disponible. Le chemin d'échec, lui, est testé — les
  réponses survivent, et l'écran l'annonce sans jargon.
- **Une seule table SQL**, aucune migration. Si tu modifies le schéma, supprime
  le fichier `.db`.
