"""Persistance SQLite du banc d'essai.

Volontairement en sqlite3 de la bibliothèque standard : c'est un banc d'essai,
pas l'application. L'application réelle garde SQLAlchemy 2.0 + Alembic.
"""

import json
import os
import random
import sqlite3
import uuid
from datetime import datetime, timezone

DOSSIER = "/data" if os.path.isdir("/data") else "."
CHEMIN = os.path.join(DOSSIER, "banc-essai.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS participation (
    uuid              TEXT PRIMARY KEY,
    prenom            TEXT NOT NULL,
    nom               TEXT NOT NULL,
    lieu              TEXT NOT NULL,
    reponses_json     TEXT NOT NULL,
    etage             INTEGER NOT NULL DEFAULT 1,
    nom_fictif        TEXT,
    peuple            TEXT,
    portrait          TEXT,
    indice            TEXT,
    fuites_noms       TEXT,
    modele            TEXT,
    duree_s           REAL,
    jetons_entree     INTEGER,
    jetons_sortie     INTEGER,
    nb_generations    INTEGER NOT NULL DEFAULT 0,
    etat              TEXT NOT NULL DEFAULT 'en_attente',
    derniere_erreur   TEXT,
    validee           INTEGER NOT NULL DEFAULT 0,
    creee_le          TEXT NOT NULL,
    modifiee_le       TEXT NOT NULL
);
"""


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connexion() -> sqlite3.Connection:
    cnx = sqlite3.connect(CHEMIN, timeout=15.0)
    cnx.row_factory = sqlite3.Row
    cnx.execute("PRAGMA journal_mode=WAL")
    cnx.execute("PRAGMA foreign_keys=ON")
    return cnx


def initialiser() -> None:
    with connexion() as cnx:
        cnx.executescript(SCHEMA)


def assigner_lieu(cnx: sqlite3.Connection, lieux: list[str]) -> str:
    """Le lieu le moins peuplé ; tirage au sort en cas d'égalité.

    Aucune considération de la table réelle : les grappes fortuites sont
    voulues, elles brouillent la reconstitution du plan de table.
    """
    effectifs = {lieu: 0 for lieu in lieux}
    for ligne in cnx.execute("SELECT lieu, COUNT(*) n FROM participation GROUP BY lieu"):
        if ligne["lieu"] in effectifs:
            effectifs[ligne["lieu"]] = ligne["n"]
    minimum = min(effectifs.values())
    return random.choice([lieu for lieu, n in effectifs.items() if n == minimum])


def creer(prenom: str, nom: str, reponses: dict, lieux: list[str]) -> str:
    identifiant = str(uuid.uuid4())
    horodatage = maintenant()
    with connexion() as cnx:
        lieu = assigner_lieu(cnx, lieux)
        cnx.execute(
            """INSERT INTO participation
               (uuid, prenom, nom, lieu, reponses_json, creee_le, modifiee_le)
               VALUES (?,?,?,?,?,?,?)""",
            (identifiant, prenom, nom, lieu, json.dumps(reponses, ensure_ascii=False),
             horodatage, horodatage),
        )
    return identifiant


def lire(identifiant: str) -> sqlite3.Row | None:
    with connexion() as cnx:
        return cnx.execute("SELECT * FROM participation WHERE uuid = ?", (identifiant,)).fetchone()


def lister(seulement_validees: bool = False) -> list[sqlite3.Row]:
    requete = "SELECT * FROM participation"
    if seulement_validees:
        requete += " WHERE validee = 1 AND portrait IS NOT NULL"
    requete += " ORDER BY lieu, creee_le"
    with connexion() as cnx:
        return cnx.execute(requete).fetchall()


def tous_les_prenoms() -> list[str]:
    with connexion() as cnx:
        lignes = cnx.execute("SELECT prenom, nom FROM participation").fetchall()
    mots: list[str] = []
    for ligne in lignes:
        mots += ligne["prenom"].split() + ligne["nom"].split()
    return mots


def enregistrer_portrait(identifiant: str, portrait: dict) -> None:
    with connexion() as cnx:
        cnx.execute(
            """UPDATE participation SET
                 nom_fictif=?, peuple=?, portrait=?, indice=?, fuites_noms=?,
                 modele=?, duree_s=?, jetons_entree=?, jetons_sortie=?,
                 nb_generations = nb_generations + 1,
                 etat='prete', derniere_erreur=NULL, modifiee_le=?
               WHERE uuid=?""",
            (portrait["nom_fictif"], portrait["peuple"], portrait["portrait"],
             portrait["indice"], json.dumps(portrait.get("fuites_noms", []), ensure_ascii=False),
             portrait.get("modele"), portrait.get("duree_s"), portrait.get("jetons_entree"),
             portrait.get("jetons_sortie"), maintenant(), identifiant),
        )


def enregistrer_echec(identifiant: str, erreur: str) -> None:
    with connexion() as cnx:
        cnx.execute(
            """UPDATE participation
               SET etat='echouee', derniere_erreur=?, nb_generations = nb_generations + 1,
                   modifiee_le=?
               WHERE uuid=?""",
            (erreur[:500], maintenant(), identifiant),
        )


def marquer_en_cours(identifiant: str) -> None:
    with connexion() as cnx:
        cnx.execute(
            "UPDATE participation SET etat='en_cours', modifiee_le=? WHERE uuid=?",
            (maintenant(), identifiant),
        )


def valider(identifiant: str) -> None:
    with connexion() as cnx:
        cnx.execute(
            "UPDATE participation SET validee=1, modifiee_le=? WHERE uuid=?",
            (maintenant(), identifiant),
        )


def ajouter_bonus(identifiant: str, reponses_bonus: dict) -> None:
    with connexion() as cnx:
        ligne = cnx.execute(
            "SELECT reponses_json FROM participation WHERE uuid=?", (identifiant,)
        ).fetchone()
        reponses = json.loads(ligne["reponses_json"])
        reponses.update(reponses_bonus)
        cnx.execute(
            """UPDATE participation
               SET reponses_json=?, etage=2, validee=0, modifiee_le=?
               WHERE uuid=?""",
            (json.dumps(reponses, ensure_ascii=False), maintenant(), identifiant),
        )
