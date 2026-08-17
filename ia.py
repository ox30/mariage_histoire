"""Appel au modèle et contrôle de la sortie.

Le portrait est un dérivé jetable : les réponses brutes restent la seule
vérité en base. Si cet appel échoue, rien n'est perdu.
"""

import json
import os
import re
import time
import unicodedata

import httpx

URL_API = "https://api.anthropic.com/v1/messages"
MODELE_DEFAUT = "claude-sonnet-5"


class ErreurGeneration(Exception):
    pass


def _normaliser(mot: str) -> str:
    sans_accent = unicodedata.normalize("NFKD", mot.lower())
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", sans_accent)


def verifier_noms(texte: str, noms_interdits: list[str]) -> list[str]:
    """Renvoie la liste des noms réels qui ont fui dans le texte généré.

    On ne corrige pas silencieusement : on signale, et l'humain tranche à la
    relecture. Un remplacement automatique produirait des phrases cassées.
    """
    mots_texte = {_normaliser(m) for m in re.findall(r"\w+", texte)}
    fuites = []
    for nom in noms_interdits:
        # « Jean-Pierre » doit être cherché en entier ET partie par partie :
        # le texte généré peut n'en reprendre qu'une moitié.
        parties = [nom] + re.split(r"[-\s']+", nom)
        for partie in parties:
            n = _normaliser(partie)
            if len(n) >= 3 and n in mots_texte:
                fuites.append(nom)
                break
    return sorted(set(fuites))


def _construire_message(config: dict, participation: dict) -> str:
    """Assemble les réponses en un bloc lisible pour le modèle."""
    lignes = [
        f"LIEU DÉJÀ ASSIGNÉ PAR LE SERVEUR : {participation['lieu']}",
        "(le personnage y a été convoqué, il ne l'a pas choisi)",
        "",
        "RÉPONSES DE LA PERSONNE :",
    ]
    reponses = participation["reponses"]
    for bloc in ("obligatoires", "bonus"):
        for q in config[bloc]:
            valeur = reponses.get(q["cle"])
            if valeur:
                lignes.append(f"- {q['question']} → {valeur}")
    lignes += [
        "",
        "NOMS RÉELS STRICTEMENT INTERDITS EN SORTIE :",
        ", ".join(participation["noms_interdits"]) or "(aucun)",
    ]
    return "\n".join(lignes)


def generer(config: dict, participation: dict) -> dict:
    """Appelle le modèle et renvoie le portrait validé.

    Trois tentatives, attente croissante — même politique que la file de
    tâches de l'application réelle (EX-ARC-13).
    """
    cle = os.environ.get("ANTHROPIC_API_KEY")
    if not cle:
        raise ErreurGeneration("ANTHROPIC_API_KEY absente de l'environnement")

    modele = os.environ.get("MODELE_IA", MODELE_DEFAUT)
    corps = {
        "model": modele,
        "max_tokens": 1200,
        "system": config["contrat"],
        "messages": [{"role": "user", "content": _construire_message(config, participation)}],
    }
    entetes = {
        "x-api-key": cle,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    derniere_erreur = ""
    for tentative in range(3):
        if tentative:
            time.sleep(2 ** tentative)
        try:
            debut = time.monotonic()
            reponse = httpx.post(URL_API, json=corps, headers=entetes, timeout=60.0)
            duree = time.monotonic() - debut
            if reponse.status_code != 200:
                derniere_erreur = f"HTTP {reponse.status_code} — {reponse.text[:300]}"
                continue
            charge = reponse.json()
        except Exception as exc:  # réseau, timeout, JSON illisible
            derniere_erreur = f"{type(exc).__name__} — {exc}"
            continue

        brut = "".join(
            bloc.get("text", "") for bloc in charge.get("content", []) if bloc.get("type") == "text"
        ).strip()
        brut = re.sub(r"^```(?:json)?|```$", "", brut, flags=re.MULTILINE).strip()

        try:
            portrait = json.loads(brut)
        except json.JSONDecodeError:
            derniere_erreur = f"JSON illisible : {brut[:300]}"
            continue

        manquants = [c for c in ("nom_fictif", "peuple", "portrait", "indice") if not portrait.get(c)]
        if manquants:
            derniere_erreur = f"champs manquants : {', '.join(manquants)}"
            continue

        peuple = _normaliser(portrait["peuple"])
        if peuple not in {_normaliser(p) for p in config["peuples"]}:
            derniere_erreur = f"peuple hors liste : {portrait['peuple']}"
            continue

        usage = charge.get("usage", {})
        portrait["modele"] = modele
        portrait["duree_s"] = round(duree, 1)
        portrait["jetons_entree"] = usage.get("input_tokens")
        portrait["jetons_sortie"] = usage.get("output_tokens")
        portrait["fuites_noms"] = verifier_noms(
            portrait["portrait"] + " " + portrait["indice"], participation["noms_interdits"]
        )
        return portrait

    raise ErreurGeneration(derniere_erreur or "échec inconnu")
