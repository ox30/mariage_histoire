"""Tests de fumée du banc d'essai. Lancer : python test_parcours.py"""
import base64, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
from fastapi.testclient import TestClient
import main, base_donnees as bd

import contextlib
ctx = TestClient(main.app); ctx.__enter__(); c = ctx
assert c.get("/").status_code == 200, "accueil"
r = c.post("/questionnaire", data={"prenom": "Florian", "nom": "Test"})
assert r.status_code == 200 and "Quel est ton métier" in r.text, "questionnaire"
assert r.text.count('class="ecran') == 7, r.text.count('class="ecran')

reponses = {
    "prenom": "Florian", "nom": "Test",
    "metier": "opérateur du trafic ferroviaire",
    "attachement": "Un travail fait proprement",
    "defaut": "Je veux tout contrôler",
    "objet": "mon carnet de notes",
    "allegeance": "La Lumière",
    "souvenir": "le soir où on a raté le dernier train ensemble",
}
r = c.post("/valider", data=reponses, follow_redirects=False)
assert r.status_code == 303, r.status_code
uuid = r.headers["location"].split("/")[-1]

r = c.get(f"/portrait/{uuid}")
assert r.status_code == 200
time.sleep(1.5)
r = c.get(f"/portrait/{uuid}/etat")
print("état après tentative sans clé :", bd.lire(uuid)["etat"])
assert "ANTHROPIC_API_KEY absente" in r.text, r.text[:400]

# les réponses survivent à l'échec de génération : c'est le point important
ligne = bd.lire(uuid)
assert "opérateur du trafic" in ligne["reponses_json"]
assert ligne["lieu"] in main.CONFIG["lieux"]

# pages protégées
auth = {"Authorization": "Basic " + base64.b64encode(b"a:secret").decode()}
assert c.get("/tableau").status_code == 401
assert c.get("/tableau", headers=auth).status_code == 200
assert c.get("/deviner", headers=auth).status_code == 200
assert c.get("/tableau/export.json", headers=auth).status_code == 200

# bonus
r = c.post(f"/portrait/{uuid}/valider", follow_redirects=False)
assert r.status_code == 303 and "/bonus/" in r.headers["location"]
r = c.get(f"/bonus/{uuid}/questions")
assert "Une phrase que tu répètes" in r.text
r = c.post(f"/bonus/{uuid}", data={"phrase": "on verra bien", "lien": "Collègue"}, follow_redirects=False)
assert r.status_code == 303
assert bd.lire(uuid)["etage"] == 2 and "on verra bien" in bd.lire(uuid)["reponses_json"]

# répartition des lieux : 30 créations, écart maximal de 1
for i in range(30):
    bd.creer(f"P{i}", "X", {"metier": "x"}, main.CONFIG["lieux"])
from collections import Counter
compte = Counter(p["lieu"] for p in bd.lister())
print("répartition :", sorted(compte.values()))
assert max(compte.values()) - min(compte.values()) <= 1, compte
print("TOUT PASSE")

# --- Sélecteur préalable et prénoms des mariés ------------------------------
import importlib
os.environ["PRENOM_MARIEE"] = "Delphine"
os.environ["PRENOM_MARIE"] = "Jérémy"
importlib.reload(main)
c2 = TestClient(main.app); c2.__enter__()

r = c2.post("/questionnaire", data={"prenom": "Ana", "nom": "Test"})
assert "Delphine" in r.text and "Jérémy" in r.text, "prénoms substitués dans les libellés"
assert 'name="souvenir_avec"' in r.text, "champ du sélecteur préalable"
assert 'class="choix prealable"' in r.text, "boutons du sélecteur préalable"

donnees = dict(reponses); donnees.update({"prenom": "Ana", "nom": "Test",
                                          "souvenir_avec": "Delphine"})
r = c2.post("/valider", data=donnees, follow_redirects=False)
uid2 = r.headers["location"].split("/")[-1]
assert '"souvenir_avec": "Delphine"' in bd.lire(uid2)["reponses_json"], "réponse préalable stockée"

# le message envoyé au modèle porte les prénoms et le sélecteur
import json as _json, ia
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Isengard", "reponses": _json.loads(bd.lire(uid2)["reponses_json"]),
    "noms_interdits": ["Delphine"], "couple": main.COUPLE})
assert "la mariée s'appelle Delphine" in msg
assert "Ce souvenir, c'est avec… → Delphine" in msg
assert "jamais écrire" in msg
print("TOUT PASSE (2)")

# --- Bifurcation avant génération -------------------------------------------
r = c2.post("/questionnaire", data={"prenom": "Bea", "nom": "Test"})
assert 'data-suite="bonus"' in r.text and "Créer mon personnage" in r.text, "écran de bifurcation"

d = dict(donnees); d.update({"prenom": "Bea", "nom": "Test", "suite": "bonus"})
r = c2.post("/valider", data=d, follow_redirects=False)
assert "/bonus/" in r.headers["location"] and "/questions" in r.headers["location"]
uid3 = r.headers["location"].split("/")[2]
assert bd.lire(uid3)["etat"] == "brouillon", bd.lire(uid3)["etat"]

r = c2.get(f"/portrait/{uid3}")
assert "Il reste six questions" in r.text, "état brouillon annoncé"

r = c2.get(f"/bonus/{uid3}/questions")
assert "sans ces questions" in r.text and "facultatif = true" in r.text

# sortie sans répondre : étage reste à 1, la génération part quand même
r = c2.post(f"/bonus/{uid3}", data={"suite": "sortie"}, follow_redirects=False)
assert r.status_code == 303
assert bd.lire(uid3)["etage"] == 1, "aucune réponse complémentaire → étage 1"
assert bd.lire(uid3)["etat"] in ("en_cours", "echouee", "en_attente")

# le volume reçu est annoncé au modèle
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Edoras", "reponses": _json.loads(bd.lire(uid3)["reponses_json"]),
    "noms_interdits": [], "couple": main.COUPLE})
assert "sans complément" in msg and "Exploite-les toutes" in msg

d2 = dict(donnees); d2.update({"prenom": "Cyd", "nom": "Test", "suite": "bonus"})
uid4 = c2.post("/valider", data=d2, follow_redirects=False).headers["location"].split("/")[2]
c2.post(f"/bonus/{uid4}", data={"phrase": "on verra", "talent": "je siffle"},
        follow_redirects=False)
assert bd.lire(uid4)["etage"] == 2
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Edoras", "reponses": _json.loads(bd.lire(uid4)["reponses_json"]),
    "noms_interdits": [], "couple": main.COUPLE})
assert "complémentaires" in msg and "laisse les autres" in msg
# on ne repropose pas le second étage à qui l'a déjà donné
assert c2.get(f"/bonus/{uid4}", follow_redirects=False).status_code == 303
print("TOUT PASSE (3)")

# --- Boutons de la bifurcation : libellé et action doivent concorder ---------
r = c2.post("/questionnaire", data={"prenom": "Dan", "nom": "Test"})
assert 'name="suite" id="champ-suite"' in r.text, "le choix passe par un champ caché"
assert r.text.count('data-suite="maintenant"') == 1
assert r.text.count('data-suite="bonus"') == 1
# aucun bouton d'envoi ne doit être capté par la navigation arrière
import re as _re
for bloc in _re.findall(r'<button[^>]*data-arriere[^>]*>', r.text):
    assert 'type="button"' in bloc, bloc
for bloc in _re.findall(r'<button[^>]*class="[^"]*envoi[^"]*"[^>]*>', r.text):
    assert "data-arriere" not in bloc, bloc

# le champ caché pilote réellement le routage
d = dict(donnees); d.update({"prenom": "Dan", "nom": "Test", "suite": "bonus"})
assert "/bonus/" in c2.post("/valider", data=d, follow_redirects=False).headers["location"]
d["suite"] = "maintenant"
assert "/portrait/" in c2.post("/valider", data=d, follow_redirects=False).headers["location"]

# sortie du questionnaire complémentaire par le champ caché
d2 = dict(donnees); d2.update({"prenom": "Eve", "nom": "Test", "suite": "bonus"})
uid5 = c2.post("/valider", data=d2, follow_redirects=False).headers["location"].split("/")[2]
r = c2.get(f"/bonus/{uid5}/questions")
assert 'data-suite="sortie"' in r.text and 'class="retour envoi"' in r.text
c2.post(f"/bonus/{uid5}", data={"suite": "sortie", "phrase": "ignorée"},
        follow_redirects=False)
assert bd.lire(uid5)["etage"] == 1, "la sortie ne retient aucune réponse complémentaire"
assert "ignorée" not in bd.lire(uid5)["reponses_json"]

# troncature diagnostiquée comme telle
assert ia.MODELE_DEFAUT == "claude-sonnet-5"
print("TOUT PASSE (4)")

# --- Cloisonnement des réponses par destination -----------------------------
reponses_completes = {
    "metier": "Chef de groupe des opérateurs du trafic",
    "attachement": "Un travail fait proprement",
    "defaut": "Je veux tout contrôler",
    "objet": "Mes clubs de golf",
    "allegeance": "L'Ombre",
    "souvenir": "Mon épouse est la soeur de la mariée. Les repas en Valais.",
    "souvenir_avec": "Delphine",
    "lien": "Famille de la mariée",
    "role_groupe": "Observe en silence",
    "colere": "Le travail bâclé",
    "talent": "J'ai de la créativité.",
    "phrase": "Je vais au golf",
    "souhait": "Tout le bonheur du monde.",
}
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Edoras", "reponses": reponses_completes,
    "noms_interdits": [], "couple": main.COUPLE})

bloc_portrait = msg.split("RÉSERVÉ À")[0]
assert "Mes clubs de golf" in bloc_portrait
assert "Famille de la mariée" in bloc_portrait, "le lien nourrit le portrait, transposé"
assert "Tout le bonheur du monde" not in msg, "le vœu n'atteint jamais le modèle"
assert "souhaites-tu" not in msg, "ni la question du vœu"
# le décompte annoncé ne compte que ce qui nourrit le portrait
assert "5 complémentaires" in msg, msg[-400:]

contrat = main.CONFIG["contrat"]
for regle in ("peut être nommée", "elle ne se pose jamais à plat",
              "a sa place dans le portrait, mais transposé",
              "gabarit le plus visible"):
    assert regle in contrat, regle
print("TOUT PASSE (5)")
