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
