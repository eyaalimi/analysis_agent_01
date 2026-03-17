"""
tests/test_pipeline.py
Pipeline test : Agent 1 (Analysis) → Agent 2 (Sourcing)

Simule un email entrant, le fait analyser par l'Agent 1,
puis cherche des fournisseurs tunisiens via l'Agent 2.

Usage :
    python tests/test_pipeline.py
"""

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=True)

from agents.analysis.agent import AnalysisAgent
from agents.agent_sourcing.agent import SourcingAgent

# ── Change this to test different scenarios ───────────────────────────────────
TEST_EMAIL = """
Bonjour,

Je souhaite acquérir 10 chaises de bureau ergonomiques pour notre open space.
Budget maximum : 5000 TND.
Livraison souhaitée avant le 30 avril 2026.

Merci,
"""
REQUESTER_EMAIL = "eyaaformation@gmail.com"
# ─────────────────────────────────────────────────────────────────────────────


def separator(title: str):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print('═' * 60)


def run_pipeline():
    separator("ÉTAPE 1 — Agent 1 : Analyse de l'email")
    print(f"Email reçu de : {REQUESTER_EMAIL}")
    print(f"Contenu       : {TEST_EMAIL.strip()[:120]}...\n")

    agent1 = AnalysisAgent()
    spec = agent1.analyze(TEST_EMAIL, REQUESTER_EMAIL)
    spec_dict = asdict(spec)

    print(f"✅  Résultat Agent 1 :")
    print(f"    Produit   : {spec.product}")
    print(f"    Catégorie : {spec.category}")
    print(f"    Quantité  : {spec.quantity} {spec.unit or ''}")
    print(f"    Budget    : {spec.budget_min or 'N/A'} – {spec.budget_max or 'N/A'} TND")
    print(f"    Deadline  : {spec.deadline or 'Non précisée'}")
    print(f"    Valide    : {spec.is_valid}")
    if not spec.is_valid:
        print(f"    Rejet     : {spec.rejection_reason}")

    if not spec.is_valid:
        print("\n⛔  Demande invalide — pipeline arrêté.")
        return

    separator("ÉTAPE 2 — Agent 2 : Sourcing fournisseurs Tunisie")
    print(f"Recherche de fournisseurs pour : {spec.product}\n")

    agent2 = SourcingAgent()
    result = agent2.source(spec_dict)

    if not result.suppliers:
        print("⚠️   Aucun fournisseur trouvé.")
    else:
        print(f"✅  {len(result.suppliers)} fournisseur(s) trouvé(s) :\n")
        for i, s in enumerate(result.suppliers, 1):
            print(f"  [{i}] {s.name}")
            print(f"      Website : {s.website}")
            print(f"      Email   : {s.email or 'N/A'}")
            print(f"      Pays    : {s.country}")
            print(f"      Score   : {s.relevance_score:.2f}")
            print()

    # Save full pipeline result to outputs/
    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"pipeline_{ts}.json"

    pipeline_result = {
        "agent1_spec": spec_dict,
        "agent2_suppliers": asdict(result),
        "pipeline_timestamp": datetime.now().isoformat(),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pipeline_result, f, ensure_ascii=False, indent=2, default=str)

    separator("RÉSULTAT SAUVEGARDÉ")
    print(f"💾  {output_path}")


if __name__ == "__main__":
    run_pipeline()
