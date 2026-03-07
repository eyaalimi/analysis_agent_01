"""
tests/test_analysis_agent.py
Quick test for the Analysis Agent — no DB or email required.
Run with: python tests/test_analysis_agent.py
"""
import sys
import os

# Make sure the project root is on PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.analysis.agent import AnalysisAgent


def run_test(label: str, email_body: str, requester_email: str):
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"{'='*60}")
    agent = AnalysisAgent()
    result = agent.analyze(email_body, requester_email)
    print(f"  is_valid        : {result.is_valid}")
    print(f"  product         : {result.product}")
    print(f"  category        : {result.category}")
    print(f"  quantity        : {result.quantity} {result.unit}")
    print(f"  budget          : {result.budget_min} – {result.budget_max} TND")
    print(f"  deadline        : {result.deadline}")
    print(f"  requester_email : {result.requester_email}")
    if not result.is_valid:
        print(f"  rejection_reason: {result.rejection_reason}")
    return result


if __name__ == "__main__":
    # ── Test 1: Clear, complete request in French ─────────────────
    run_test(
        label="Complete French request",
        email_body="""
Bonjour,

Notre département a besoin de 200 ramettes de papier A4 80g/m² 
pour nos imprimantes. Budget disponible entre 400 et 600 TND.
Livraison souhaitée avant le 15 avril 2026.

Merci de nous envoyer vos meilleures offres.

Cordialement,
Ahmed Ben Ali
""",
        requester_email="ahmed.benali@entreprise.tn",
    )

    # ── Test 2: Request in English ────────────────────────────────
    run_test(
        label="English request",
        email_body="""
Hello,

We need to purchase 10 laptops for our development team.
Budget: around 25,000 TND. Please include delivery time in your offer.

Best regards,
IT Department
""",
        requester_email="it@company.tn",
    )

    # ── Test 3: Incomplete / ambiguous request ────────────────────
    run_test(
        label="Ambiguous / incomplete request (should be rejected)",
        email_body="Bonjour, j'ai besoin de quelque chose pour le bureau.",
        requester_email="user@example.tn",
    )

    print("\n✅ All tests done.")
