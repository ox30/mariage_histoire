"""Banc d'essai « Terre du Milieu ».

Objectif unique : vérifier deux choses avant d'écrire le cahier des charges
v3.0 — que les invités savent répondre seuls aux six questions, et que les
portraits produits sont devinables par les mariés.

Ce n'est pas l'application. Pas de mot de passe de table, pas de photo, pas de
quotas, pas de file de tâches persistée. Le parcours et le prompt, en revanche,
sont ceux de la version réelle.
"""

import json
import os
import secrets
import threading
from contextlib import asynccontextmanager

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import base_donnees as bd
import ia

RACINE = os.path.dirname(os.path.abspath(__file__))
MAX_GENERATIONS = 3

# Prénoms des mariés : en variables d'environnement, jamais dans le dépôt, pour
# que l'outil serve à un autre mariage sans toucher au code ni à la config.
COUPLE = {
    "mariee": os.environ.get("PRENOM_MARIEE", "la mariée"),
    "marie": os.environ.get("PRENOM_MARIE", "le marié"),
}


def _substituer(valeur):
    """Remplace {mariee} et {marie} partout dans la configuration chargée.

    Remplacement explicite et non `str.format` : le contrat de style contient
    des accolades JSON que format interpréterait comme des champs.
    """
    if isinstance(valeur, str):
        for cle, prenom in COUPLE.items():
            valeur = valeur.replace("{" + cle + "}", prenom)
        return valeur
    if isinstance(valeur, list):
        return [_substituer(v) for v in valeur]
    if isinstance(valeur, dict):
        return {c: _substituer(v) for c, v in valeur.items()}
    return valeur


CONFIG = _substituer(
    yaml.safe_load(open(os.path.join(RACINE, "questions.yaml"), encoding="utf-8"))
)

@asynccontextmanager
async def cycle_de_vie(_: FastAPI):
    bd.initialiser()
    yield


app = FastAPI(title="Banc d'essai Terre du Milieu", lifespan=cycle_de_vie)
app.mount("/static", StaticFiles(directory=os.path.join(RACINE, "static")), name="static")
gabarits = Jinja2Templates(directory=os.path.join(RACINE, "templates"))
gabarits.env.autoescape = True

securite = HTTPBasic()


def admin(identifiants: HTTPBasicCredentials = Depends(securite)) -> str:
    attendu = os.environ.get("MOT_DE_PASSE_ADMIN", "")
    if not attendu or not secrets.compare_digest(identifiants.password, attendu):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return identifiants.username


# --------------------------------------------------------------------------- #
# Génération, hors du fil de la requête : l'invité n'attend jamais l'API pour
# que sa contribution existe en base.
# --------------------------------------------------------------------------- #

def _lancer_generation(identifiant: str) -> None:
    def travail() -> None:
        ligne = bd.lire(identifiant)
        if ligne is None:
            return
        bd.marquer_en_cours(identifiant)
        interdits = [m for m in bd.tous_les_prenoms() if len(m) >= 3]
        # Les prénoms des mariés servent à comprendre les réponses, jamais à
        # être écrits : ils sont donc aussi interdits en sortie.
        interdits += [v for v in COUPLE.values() if len(v) >= 3]
        try:
            portrait = ia.generer(
                CONFIG,
                {
                    "lieu": ligne["lieu"],
                    "reponses": json.loads(ligne["reponses_json"]),
                    "noms_interdits": interdits,
                    "couple": COUPLE,
                },
            )
            bd.enregistrer_portrait(identifiant, portrait)
        except Exception as exc:
            bd.enregistrer_echec(identifiant, f"{type(exc).__name__} — {exc}")

    threading.Thread(target=travail, daemon=True).start()


def _reponses_du_formulaire(donnees: dict, bloc: str) -> dict:
    reponses = {}
    for question in CONFIG[bloc]:
        prealable = question.get("prealable")
        if prealable:
            valeur = (donnees.get(prealable["cle"]) or "").strip()
            if valeur:
                reponses[prealable["cle"]] = valeur[:60]
        valeur = (donnees.get(question["cle"]) or "").strip()
        if valeur:
            limite = question.get("limite", 200)
            reponses[question["cle"]] = valeur[:limite]
    return reponses


# --------------------------------------------------------------------------- #
# Parcours invité
# --------------------------------------------------------------------------- #

@app.get("/", response_class=HTMLResponse)
def accueil(request: Request):
    return gabarits.TemplateResponse("accueil.html", {"request": request})


@app.post("/questionnaire", response_class=HTMLResponse)
def questionnaire(request: Request, prenom: str = Form(...), nom: str = Form(...)):
    return gabarits.TemplateResponse(
        "questionnaire.html",
        {
            "request": request,
            "prenom": prenom.strip()[:40],
            "nom": nom.strip()[:40],
            "questions": CONFIG["obligatoires"],
            "action": "/valider",
            "titre": "Six questions",
            "bifurcation": True,
            "facultatif": False,
        },
    )


@app.post("/valider")
async def valider(request: Request):
    donnees = dict(await request.form())
    prenom = (donnees.get("prenom") or "").strip()[:40]
    nom = (donnees.get("nom") or "").strip()[:40]
    if not prenom or not nom:
        return RedirectResponse("/", status_code=303)
    reponses = _reponses_du_formulaire(donnees, "obligatoires")

    # Le choix se fait avant la génération : celui qui veut en dire plus n'attend
    # pas deux fois, et on ne lui demande pas de rouvrir un cadeau déjà ouvert.
    if donnees.get("suite") == "bonus":
        identifiant = bd.creer(prenom, nom, reponses, CONFIG["lieux"], etat="brouillon")
        return RedirectResponse(f"/bonus/{identifiant}/questions", status_code=303)

    identifiant = bd.creer(prenom, nom, reponses, CONFIG["lieux"])
    _lancer_generation(identifiant)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


@app.get("/portrait/{identifiant}", response_class=HTMLResponse)
def portrait(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse(
        "portrait.html",
        {"request": request, "p": ligne, "max_generations": MAX_GENERATIONS},
    )


@app.get("/portrait/{identifiant}/etat", response_class=HTMLResponse)
def etat_portrait(request: Request, identifiant: str):
    """Fragment interrogé par HTMX pendant l'écriture."""
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse(
        "fragment_portrait.html",
        {"request": request, "p": ligne, "max_generations": MAX_GENERATIONS},
    )


@app.post("/portrait/{identifiant}/regenerer")
def regenerer(identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    if ligne["nb_generations"] < MAX_GENERATIONS:
        _lancer_generation(identifiant)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


@app.post("/portrait/{identifiant}/valider")
def valider_portrait(identifiant: str):
    bd.valider(identifiant)
    return RedirectResponse(f"/bonus/{identifiant}", status_code=303)


@app.get("/bonus/{identifiant}", response_class=HTMLResponse)
def proposer_bonus(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    if ligne["etage"] == 2:
        return RedirectResponse("/fin", status_code=303)
    return gabarits.TemplateResponse(
        "bonus_intro.html", {"request": request, "p": ligne}
    )


@app.get("/bonus/{identifiant}/questions", response_class=HTMLResponse)
def questions_bonus(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse(
        "questionnaire.html",
        {
            "request": request,
            "prenom": ligne["prenom"],
            "nom": ligne["nom"],
            "questions": CONFIG["bonus"],
            "action": f"/bonus/{identifiant}",
            "titre": "Six de plus",
            "bifurcation": False,
            "facultatif": True,
        },
    )


@app.post("/bonus/{identifiant}")
async def enregistrer_bonus(request: Request, identifiant: str):
    donnees = dict(await request.form())
    reponses = {} if donnees.get("sortie") else _reponses_du_formulaire(donnees, "bonus")
    bd.ajouter_bonus(identifiant, reponses)
    _lancer_generation(identifiant)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


@app.get("/fin", response_class=HTMLResponse)
def fin(request: Request):
    return gabarits.TemplateResponse("fin.html", {"request": request})


# --------------------------------------------------------------------------- #
# Pages de test — c'est ici que le banc d'essai gagne son nom
# --------------------------------------------------------------------------- #

@app.get("/deviner", response_class=HTMLResponse)
def deviner(request: Request, _: str = Depends(admin)):
    """La page à montrer à quelqu'un qui connaît les participants."""
    participations = [p for p in bd.lister() if p["portrait"]]
    par_lieu: dict[str, list] = {}
    for p in participations:
        par_lieu.setdefault(p["lieu"], []).append(p)
    return gabarits.TemplateResponse(
        "deviner.html", {"request": request, "par_lieu": par_lieu, "total": len(participations)}
    )


@app.get("/tableau", response_class=HTMLResponse)
def tableau(request: Request, _: str = Depends(admin)):
    participations = bd.lister()
    jetons_entree = sum(p["jetons_entree"] or 0 for p in participations)
    jetons_sortie = sum(p["jetons_sortie"] or 0 for p in participations)
    durees = [p["duree_s"] for p in participations if p["duree_s"]]
    return gabarits.TemplateResponse(
        "tableau.html",
        {
            "request": request,
            "participations": participations,
            "jetons_entree": jetons_entree,
            "jetons_sortie": jetons_sortie,
            "duree_moyenne": round(sum(durees) / len(durees), 1) if durees else None,
            "duree_max": max(durees) if durees else None,
            "echecs": sum(1 for p in participations if p["etat"] == "echouee"),
            "fuites": sum(1 for p in participations if p["fuites_noms"] not in (None, "[]")),
        },
    )


@app.get("/tableau/export.json")
def export(_: str = Depends(admin)):
    return JSONResponse(
        [
            {
                "uuid": p["uuid"],
                "prenom": p["prenom"],
                "nom": p["nom"],
                "lieu": p["lieu"],
                "etage": p["etage"],
                "reponses": json.loads(p["reponses_json"]),
                "nom_fictif": p["nom_fictif"],
                "peuple": p["peuple"],
                "portrait": p["portrait"],
                "indice": p["indice"],
                "fuites_noms": json.loads(p["fuites_noms"] or "[]"),
                "modele": p["modele"],
                "duree_s": p["duree_s"],
                "jetons": [p["jetons_entree"], p["jetons_sortie"]],
                "nb_generations": p["nb_generations"],
                "etat": p["etat"],
                "derniere_erreur": p["derniere_erreur"],
            }
            for p in bd.lister()
        ]
    )
