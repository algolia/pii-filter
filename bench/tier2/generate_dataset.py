#!/usr/bin/env python3
"""Deterministic French e-commerce PII mini-eval generator (ground truth by construction).

Synthesizes n~200 labeled samples for PERSON and ADDRESS detection, in the two shapes
this toolkit actually sees: search-query-shaped and support-message-shaped, plus ~25%
PII-free negatives. Ground truth is exact by construction: we place known values into
templates and record their [start, end) char spans.

Sources:
  - ADDRESS: fully synthetic (synth_addresses below). Invented commune names, none
    of which is in the official commune list (checked against geo.api.gouv.fr on
    2026-11-16), generic street names, and a Lozere-style 48xxx postal code. No
    address is a real place.
  - PERSON first names: INSEE "fichier des prenoms depuis 1900", national file (parquet mirror).
    https://static.data.gouv.fr/resources/base-prenoms-insee-format-parquet/20231121-161435/prenoms-nat2022.parquet
  - PERSON surnames: the most common French family names, per INSEE published rankings
    (baked below as a documented public list; INSEE patronyme micro-files are not a
    single stable download, so we embed the ranking to keep the generator reproducible).

Names are random pairs of common first names and common surnames, so no
sample describes a real person. Raw data is NOT committed (it is a data dump); only
the generated JSON is. Missing raw files are downloaded on first run into --data-dir (default: this script's data/ dir).

Requires: pandas, pyarrow (see requirements.txt). Run:
  python generate_dataset.py --out dataset.json --n 200 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data"

PRENOMS_URL = (
    "https://static.data.gouv.fr/resources/base-prenoms-insee-format-parquet/"
    "20231121-161435/prenoms-nat2022.parquet"
)
PRENOMS_FILE = "prenoms-nat2022.parquet"

# INSEE most-common French family names (documented public ranking). Kept ASCII-clean
# for stable string matching; a representative slice of the ~200 most frequent patronymes.
SURNAMES = [
    "Martin", "Bernard", "Thomas", "Petit", "Robert", "Richard", "Durand", "Dubois",
    "Moreau", "Laurent", "Simon", "Michel", "Lefebvre", "Leroy", "Roux", "David",
    "Bertrand", "Morel", "Fournier", "Girard", "Bonnet", "Dupont", "Lambert", "Fontaine",
    "Rousseau", "Vincent", "Muller", "Lefevre", "Faure", "Andre", "Mercier", "Blanc",
    "Guerin", "Boyer", "Garnier", "Chevalier", "Francois", "Legrand", "Gauthier", "Garcia",
    "Perrin", "Robin", "Clement", "Morin", "Nicolas", "Henry", "Roussel", "Mathieu",
    "Gautier", "Masson", "Marchand", "Duval", "Denis", "Dumont", "Marie", "Lemaire",
    "Noel", "Meyer", "Dufour", "Meunier", "Brun", "Blanchard", "Giraud", "Joly", "Riviere",
    "Lucas", "Brunet", "Gaillard", "Barbier", "Arnaud", "Martinez", "Gerard", "Roche",
    "Renard", "Schmitt", "Roy", "Leroux", "Colin", "Vidal", "Caron", "Picard", "Roger",
    "Fabre", "Aubert", "Lemoine", "Renaud", "Dumas", "Lacroix", "Olivier", "Philippe",
    "Bourgeois", "Pierre", "Benoit", "Rey", "Leclerc", "Rolland", "Guillaume", "Lopez",
    "Jean", "Dupuy", "Guillot", "Hubert", "Berger", "Sanchez", "Dupuis", "Moulin",
    "Louis", "Deschamps", "Huet", "Vasseur", "Perez", "Boucher", "Fleury", "Klein",
]

# Invented communes: none is in the official commune list (geo.api.gouv.fr, 2026-11-16).
COMMUNES = [
    "Valcombre", "Montaurès", "Lescalmes", "Fontbelade", "Le Puech-Varel",
    "Saint-Aurel-de-Brousse", "Combefraîche", "Brugeiroles", "Sainte-Ondine-du-Causse",
    "La Bastide-Ferrandal", "Rocheclare", "Mazelbrune", "Les Vernhettes-Hautes",
    "Prat-de-Lunel", "Saint-Orvald", "Castelvérine", "Aigueplane", "Le Mas-Fouillade",
    "Peyrelongue-sur-Lot", "Chanteval-le-Haut", "Bellaudière", "Vialarède",
    "Font-Romeyre", "Saint-Ivarel-d'Olt", "Malescombe",
]
STREET_NOUNS = [
    "de la Forge", "des Genêts", "du Moulin", "du Lavoir", "de la Fontaine", "des Écoles",
    "de la Calade", "des Tilleuls", "du Four", "de la Croix", "des Prés", "du Pont",
    "de l'Église", "des Jardins", "du Couvent", "de la Tour",
]
# Street-type mix typical of small-town French addresses: rue, route, chemin, impasse, place, avenue.
STREET_TYPES = ["rue"] * 43 + ["route"] * 26 + ["chemin"] * 14 + ["impasse"] * 9 + ["place"] * 7 + ["avenue"] * 2
POSTAL_CODES = ["48000", "48100", "48110", "48130", "48150", "48170", "48190", "48200",
                "48220", "48230", "48250", "48300", "48310", "48340", "48400", "48500"]

CIVILITIES = ["M.", "Mme", "Mlle"]


@dataclass
class Ent:
    entity: str  # "PERSON" | "ADDRESS"
    start: int
    end: int
    value: str


@dataclass
class Sample:
    text: str
    entities: list[Ent] = field(default_factory=list)
    template_kind: str = ""   # "search" | "support" | "negative"
    person_form: str = "none"  # "full" | "partial" | "none"
    has_address: bool = False


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url} -> {dest}")
    if url.endswith(".gz"):
        import gzip
        import shutil

        tmp = dest.with_suffix(dest.suffix + ".gz")
        urllib.request.urlretrieve(url, tmp)
        with gzip.open(tmp, "rb") as fin, open(dest, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        tmp.unlink()
    else:
        urllib.request.urlretrieve(url, dest)


def load_first_names(data_dir: Path, per_sex: int = 300) -> tuple[list[str], list[str]]:
    """Return (male, female) common first names, Title-cased, ASCII-normalised where simple."""
    import pandas as pd

    path = data_dir / PRENOMS_FILE
    if not path.exists():
        _download(PRENOMS_URL, path)
    df = pd.read_parquet(path)
    df = df[df["preusuel"] != "_PRENOMS_RARES"]
    df = df[df["annais"] != "XXXX"]
    # recent births only -> realistic contemporary names
    df = df[pd.to_numeric(df["annais"], errors="coerce") >= 1980]
    agg = df.groupby(["sexe", "preusuel"], as_index=False)["nombre"].sum()

    def top(sex: int) -> list[str]:
        sub = agg[agg["sexe"] == sex].sort_values("nombre", ascending=False)
        names = [str(n).strip() for n in sub["preusuel"].tolist()]
        names = [n for n in names if n.isalpha() and len(n) >= 2]
        # INSEE stores upper-case; Title-case them
        return [n.capitalize() for n in names[:per_sex]]

    return top(1), top(2)


def _de(place: str) -> str:
    for art, contracted in (("Le ", "du "), ("Les ", "des "), ("La ", "de la ")):
        if place.startswith(art):
            return contracted + place[len(art):]
    return "de " + place


def synth_addresses(seed: int, n: int = 4000) -> list[str]:
    """n invented addresses, from their own RNG so the main draw sequence is unchanged."""
    rng = random.Random(f"addresses-{seed}")
    out: list[str] = []
    for _ in range(n):
        kind = rng.choice(STREET_TYPES)
        commune = rng.choice(COMMUNES)
        if kind == "route":
            voie = "route " + _de(rng.choice([c for c in COMMUNES if c != commune]))
        elif kind == "chemin" and rng.random() < 0.5:
            voie = "chemin " + _de(rng.choice([c for c in COMMUNES if c != commune]))
        else:
            voie = f"{kind} {rng.choice(STREET_NOUNS)}"
        numero = str(rng.randint(1, 60))
        out.append(f"{numero} {voie} {rng.choice(POSTAL_CODES)} {commune}")
    return out


# ---- templates ---------------------------------------------------------------
# Each template is a list of segments; a segment is either a literal str, or a
# 2-tuple ("PERSON"|"ADDRESS", key) that the assembler fills and records a span for.
SEARCH_TEMPLATES = [
    ["livraison ", ("PERSON",), " ", ("ADDRESS",)],
    ["commande ", ("PERSON",)],
    [("PERSON",), " ", ("ADDRESS",)],
    ["colis ", ("ADDRESS",)],
    ["ou est ma commande ", ("PERSON",)],
    ["facture ", ("PERSON",), " adresse ", ("ADDRESS",)],
    ["suivi colis ", ("PERSON",)],
    ["retour produit ", ("PERSON",), " ", ("ADDRESS",)],
]

SUPPORT_TEMPLATES = [
    ["Bonjour, je m'appelle ", ("PERSON",),
     ". Je n'ai pas recu ma commande livree au ", ("ADDRESS",),
     ". Pouvez-vous verifier le suivi ?"],
    ["Bonjour, ma commande devait etre livree chez ", ("PERSON",),
     ", ", ("ADDRESS",), ", mais le colis est marque comme perdu. Merci de votre aide."],
    ["Bonjour, je suis ", ("PERSON",),
     " et je souhaite modifier l'adresse de livraison de ma prochaine commande. "
     "Merci d'avance."],
    ["Bonjour, le colis adresse a ", ("PERSON",), " au ", ("ADDRESS",),
     " n'est jamais arrive. Que faut-il faire pour un remboursement ?"],
    ["Bonjour, pouvez-vous confirmer que la commande de ", ("PERSON",),
     " sera bien expediee cette semaine ? Le delai annonce etait de trois jours."],
    ["Bonjour, je voudrais signaler un probleme de livraison a l'adresse ",
     ("ADDRESS",), ". Le livreur n'a pas sonne. Merci."],
]

# PII-free negatives: product-search queries and generic support with no personal data.
NEGATIVES = [
    "chaussures de running femme taille 39 imperméables",
    "je cherche un manteau d'hiver homme en laine noir",
    "quel est le délai de livraison standard pour la métropole ?",
    "casque audio sans fil bluetooth réduction de bruit",
    "comment retourner un article qui ne convient pas ?",
    "sac à dos ordinateur portable 15 pouces étanche",
    "y a-t-il des frais de port pour une commande de plus de 50 euros ?",
    "table basse en bois massif style scandinave",
    "quelles sont les modalités de paiement en plusieurs fois ?",
    "robe d'été fleurie coton taille M pas chère",
    "ma commande est en retard, quel est le délai habituel de traitement ?",
    "peut-on suivre un colis sans numéro de suivi ?",
    "cafetière expresso automatique avec broyeur intégré",
    "chaussures de sécurité antidérapantes semelle renforcée",
    "quelle est la politique de remboursement en cas d'annulation ?",
    "vélo électrique pliable autonomie 60 km",
    "existe-t-il une garantie sur les produits électroménagers ?",
    "lampe de bureau LED réglable lumière chaude",
    "comment activer une carte cadeau sur mon compte ?",
    "jouets éducatifs pour enfant de trois ans en bois",
    "batterie externe 20000 mAh charge rapide USB-C",
    "puis-je changer le mode de livraison après la commande ?",
    "matelas mémoire de forme 140x190 ferme",
    "quels sont les horaires du service client le week-end ?",
]


def _title_person(first: str, surname: str, form: str) -> str:
    if form == "partial":
        # first-initial + surname, or civility + surname
        return f"{first[0]}. {surname}"
    return f"{first} {surname}"


def assemble(segments, values: dict[str, str]) -> tuple[str, list[Ent]]:
    text = ""
    ents: list[Ent] = []
    for seg in segments:
        if isinstance(seg, tuple):
            key = seg[0]
            val = values[key]
            start = len(text)
            text += val
            ents.append(Ent(entity=key, start=start, end=len(text), value=val))
        else:
            text += seg
    return text, ents


def generate(n: int, seed: int, data_dir: Path) -> list[Sample]:
    rng = random.Random(seed)
    male, female = load_first_names(data_dir)
    addresses = synth_addresses(seed)
    first_pool = male + female

    n_neg = round(n * 0.25)
    n_pii = n - n_neg
    samples: list[Sample] = []

    # negatives (cycle deterministically, shuffled)
    negs = list(NEGATIVES)
    rng.shuffle(negs)
    for i in range(n_neg):
        text = negs[i % len(negs)]
        samples.append(Sample(text=text, entities=[], template_kind="negative"))

    # PII-bearing
    for _ in range(n_pii):
        kind = rng.choice(["search", "support"])
        templates = SEARCH_TEMPLATES if kind == "search" else SUPPORT_TEMPLATES
        seg = list(rng.choice(templates))
        needs_person = any(isinstance(s, tuple) and s[0] == "PERSON" for s in seg)
        needs_address = any(isinstance(s, tuple) and s[0] == "ADDRESS" for s in seg)

        values: dict[str, str] = {}
        person_form = "none"
        if needs_person:
            first = rng.choice(first_pool)
            surname = rng.choice(SURNAMES)
            # ~40% partial (non-verbatim slice the report flags as where detectors collapse)
            if rng.random() < 0.40:
                person_form = "partial"
                if rng.random() < 0.5:
                    civ = rng.choice(CIVILITIES)
                    values["PERSON"] = f"{civ} {surname}"
                else:
                    values["PERSON"] = _title_person(first, surname, "partial")
            else:
                person_form = "full"
                values["PERSON"] = _title_person(first, surname, "full")
        if needs_address:
            values["ADDRESS"] = rng.choice(addresses)

        text, ents = assemble(seg, values)
        samples.append(Sample(
            text=text, entities=ents, template_kind=kind,
            person_form=person_form, has_address=needs_address,
        ))

    rng.shuffle(samples)
    return samples


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=HERE / "dataset.json")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    args = ap.parse_args()

    samples = generate(args.n, args.seed, args.data_dir)

    # sanity: verify every recorded span matches the text
    for s in samples:
        for e in s.entities:
            assert s.text[e.start:e.end] == e.value, (s.text, e)

    n_person = sum(1 for s in samples for e in s.entities if e.entity == "PERSON")
    n_addr = sum(1 for s in samples for e in s.entities if e.entity == "ADDRESS")
    n_partial = sum(1 for s in samples if s.person_form == "partial")
    meta = {
        "seed": args.seed,
        "n_samples": len(samples),
        "n_person_mentions": n_person,
        "n_address_mentions": n_addr,
        "n_partial_person": n_partial,
        "n_negatives": sum(1 for s in samples if s.template_kind == "negative"),
        "sources": {
            "address": "synthetic: invented communes and street names (synth_addresses)",
            "first_names": PRENOMS_URL,
            "surnames": "INSEE most-common family-name ranking (baked list, documented)",
        },
    }
    payload = {"meta": meta, "samples": [asdict(s) for s in samples]}
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}: {meta}")


if __name__ == "__main__":
    main()
