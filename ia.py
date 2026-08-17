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
    couple = participation.get("couple") or {}
    lignes = []
    if couple:
        lignes += [
            "LES MARIÉS (pour ta compréhension seulement, à ne jamais écrire) :",
            f"- la mariée s'appelle {couple.get('mariee')}",
            f"- le marié s'appelle {couple.get('marie')}",
            "Si la personne a mal orthographié l'un de ces prénoms, comprends-le",
            "sans le relever et sans le reproduire.",
            "",
        ]
    lignes += [
        f"LIEU DÉJÀ ASSIGNÉ PAR LE SERVEUR : {participation['lieu']}",
        "(le personnage y a été convoqué, il ne l'a pas choisi)",
        "",
        "RÉPONSES DE LA PERSONNE :",
    ]
    reponses = participation["reponses"]
    obligatoires_donnees = 0
    for bloc in ("obligatoires", "bonus"):
        for q in config[bloc]:
            prealable = q.get("prealable")
            if prealable and reponses.get(prealable["cle"]):
                lignes.append(f"- {prealable['question']} → {reponses[prealable['cle']]}")
            valeur = reponses.get(q["cle"])
            if valeur:
                lignes.append(f"- {q['question']} → {valeur}")
                if bloc == "obligatoires":
                    obligatoires_donnees += 1

    # La règle d'usage dépend du volume reçu : six réponses tiennent toutes en
    # 150 mots, douze non. Les six premières restent obligatoires dans les deux
    # cas — ce sont les ancres les plus fortes.
    bonus_donnees = sum(1 for q in config["bonus"] if reponses.get(q["cle"]))
    if bonus_donnees:
        lignes += [
            "",
            f"VOLUME REÇU : {obligatoires_donnees} réponses principales et "
            f"{bonus_donnees} complémentaires. Les principales doivent toutes "
            "être exploitées ; parmi les complémentaires, retiens celles qui "
            "donnent le plus de relief et laisse les autres.",
        ]
    else:
        lignes += [
            "",
            f"VOLUME REÇU : {obligatoires_donnees} réponses, sans complément. "
            "Exploite-les toutes : chacune est une prise pour deviner.",
        ]

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
        # 150 mots de portrait plus les trois autres champs tournent autour de
        # 700 jetons ; 1200 laissait le modèle se faire couper en pleine phrase,
        # ce qui produisait un JSON tronqué et donc illisible.
        "max_tokens": 2500,
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

        # Une réponse coupée au plafond n'est pas un JSON invalide : c'est un
        # portrait trop long. Le dire pour ne pas chercher au mauvais endroit.
        if charge.get("stop_reason") == "max_tokens":
            derniere_erreur = (
                "réponse tronquée au plafond de jetons — le modèle a dépassé "
                "les 150 mots demandés"
            )
            continue

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
