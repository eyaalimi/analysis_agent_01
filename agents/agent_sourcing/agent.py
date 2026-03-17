"""
agents/agent_sourcing/agent.py
Sourcing Agent — searches for real Tunisian suppliers using Tavily Search API
and returns a ranked list of supplier candidates.

Input  : ProcurementSpec dict (JSON output of Agent 1 / AnalysisAgent)
Output : SupplierList dataclass with up to 12 ranked Tunisian supplier candidates

Pattern: Same as agents/analysis/agent.py — Strands Agent + BedrockModel + @tool decorators.
"""

import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from strands import Agent, tool
from strands.models import BedrockModel

# Ensure project root is importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from logger import get_logger

logger = get_logger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a procurement sourcing specialist. Your job is to find real, qualified
suppliers for a given procurement request.

Given a procurement spec (product, category, quantity, budget, requester_email), you must:
1. Call search_suppliers(product, category) to find relevant Tunisian suppliers.
2. For each promising result, call get_supplier_contact(supplier_name, website)
   to retrieve a contact email when possible.
3. Assign a relevance_score (0.0 to 1.0) to each supplier based on:
   - Match with the requested product/category
   - Apparent company credibility (professional website, clear activity)
   - Presence of contact information
   - Proximity or relevance to the requester's sector (inferred from requester_email domain)
4. Return at most 12 suppliers, ranked by relevance_score (highest first).

You MUST return a valid JSON object with this exact structure:
{
  "suppliers": [
    {
      "name": "string — company name",
      "website": "string — company website URL",
      "country": "Tunisia",
      "email": "string or null — contact email",
      "category": "string — procurement category matching the request",
      "relevance_score": float between 0.0 and 1.0,
      "source_url": "string — URL where this supplier was found"
    }
  ],
  "query_used": "string — exact search query used",
  "search_timestamp": "string — ISO 8601 datetime"
}

Rules:
- ALL suppliers must be based in Tunisia (.tn domains preferred).
- Only include suppliers genuinely relevant to the product/category.
- Use the requester_email domain to infer the requester's industry/sector
  and prioritize suppliers that serve that sector.
- If no Tunisian suppliers are found, return an empty suppliers array.
- Return ONLY the JSON object, no extra text.
"""

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SupplierInfo:
    """Represents a single supplier candidate."""

    name: str
    website: str
    country: str
    email: Optional[str]
    category: str
    relevance_score: float
    source_url: str


@dataclass
class SupplierList:
    """Output of the Sourcing Agent."""

    suppliers: list  # list[SupplierInfo]
    query_used: str
    search_timestamp: str


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def search_suppliers(product: str, category: str, max_results: int = 12) -> str:
    """
    Search for Tunisian suppliers using Tavily Search API.

    Args:
        product: Product or service name (e.g. "wooden office desk")
        category: Procurement category (e.g. "Office Supplies")
        max_results: Maximum number of results to return (default 12)

    Returns:
        JSON array of raw search results with keys: title, url, content, score.
        Returns an empty array if Tavily key is not configured or search fails.
    """
    if not settings.tavily_api_key:
        logger.warning("Tavily API key not configured — skipping supplier search")
        return json.dumps([])

    # "Tunisie" included in both French and English to maximise Tunisian results
    query = f"{product} fournisseur Tunisie supplier Tunisia {category}"
    logger.info("Searching Tunisian suppliers via Tavily", extra={"query": query})

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "advanced",  # Deeper search for better Tunisian coverage
                "max_results": max_results,
                # Exclude generic marketplaces — we want real B2B Tunisian suppliers
                "exclude_domains": ["amazon.com", "ebay.com", "alibaba.com", "aliexpress.com"],
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

        # Return a simplified, token-efficient result list for the LLM
        simplified = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:400],  # Trim long content
                "score": round(r.get("score", 0.0), 3),
            }
            for r in data.get("results", [])
        ]
        return json.dumps(simplified, ensure_ascii=False)

    except requests.RequestException as exc:
        logger.error("Tavily search failed", extra={"error": str(exc)})
        return json.dumps([])


EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SKIP_PREFIXES = ("noreply", "no-reply", "example", "test", "donotreply", "webmaster", "info@example")

# Common contact page paths to try when scraping a supplier's website
_CONTACT_PATHS = ["/contact", "/contact-us", "/contactez-nous", "/nous-contacter", "/contact.html", "/about", "/a-propos"]


def _scrape_email_from_url(url: str) -> Optional[str]:
    """
    Fetch a URL and extract the first valid email from its HTML.
    Returns None if no email found or request fails.
    """
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ProcurementBot/1.0)"},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        text = BeautifulSoup(resp.text, "html.parser").get_text(separator=" ")
        for email in EMAIL_PATTERN.findall(text):
            if not any(email.lower().startswith(p) for p in SKIP_PREFIXES):
                return email
    except Exception:
        pass
    return None


@tool
def get_supplier_contact(supplier_name: str, website: str) -> str:
    """
    Find a supplier's contact email using two strategies:
    1. Direct scraping of the supplier's contact page (most reliable).
    2. Tavily search fallback if scraping finds nothing.

    Args:
        supplier_name: Name of the company (e.g. "Korsi.tn")
        website: Company website URL (e.g. "https://korsi.tn")

    Returns:
        JSON object with key "email" (string or null).
    """
    logger.info("Looking up supplier contact", extra={"supplier": supplier_name, "website": website})

    base = website.rstrip("/")

    # ── Strategy 1: direct page scraping ──────────────────────────────────────
    # Try common contact page paths on the supplier's website
    for path in _CONTACT_PATHS:
        email = _scrape_email_from_url(f"{base}{path}")
        if email:
            logger.info("Email found via scraping", extra={"supplier": supplier_name, "email": email})
            return json.dumps({"email": email})

    # Also try the homepage itself
    email = _scrape_email_from_url(base)
    if email:
        logger.info("Email found on homepage", extra={"supplier": supplier_name, "email": email})
        return json.dumps({"email": email})

    # ── Strategy 2: Tavily fallback ────────────────────────────────────────────
    if settings.tavily_api_key:
        try:
            domain = base.replace("https://", "").replace("http://", "").split("/")[0]
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": f"{supplier_name} email contact",
                    "search_depth": "basic",
                    "max_results": 3,
                    "include_domains": [domain] if domain else [],
                },
                timeout=10,
            )
            response.raise_for_status()
            for result in response.json().get("results", []):
                for email in EMAIL_PATTERN.findall(result.get("content", "")):
                    if not any(email.lower().startswith(p) for p in SKIP_PREFIXES):
                        logger.info("Email found via Tavily", extra={"supplier": supplier_name, "email": email})
                        return json.dumps({"email": email})
        except requests.RequestException as exc:
            logger.warning("Tavily contact fallback failed", extra={"error": str(exc)})

    logger.info("No email found", extra={"supplier": supplier_name})
    return json.dumps({"email": None})


# ── Helper ────────────────────────────────────────────────────────────────────

def _extract_first_json_object(raw: str) -> Optional[str]:
    """Return the first balanced JSON object found in text, or None."""
    start = raw.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i, ch in enumerate(raw[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start: i + 1]

    return None


# ── Agent class ───────────────────────────────────────────────────────────────

class SourcingAgent:
    """Finds qualified suppliers for a ProcurementSpec using Tavily Search."""

    def __init__(self):
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
        )
        self._agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=[
                search_suppliers,
                get_supplier_contact,
            ],
        )

    def source(self, procurement_spec: dict) -> SupplierList:
        """
        Find Tunisian suppliers for a validated ProcurementSpec.

        Args:
            procurement_spec: dict — output of AnalysisAgent.analyze() (must have is_valid=True)
                              Must include requester_email to help contextualise the search.

        Returns:
            SupplierList with up to 12 ranked Tunisian supplier candidates.
        """
        product = procurement_spec.get("product", "")
        category = procurement_spec.get("category", "")
        budget_max = procurement_spec.get("budget_max")
        deadline = procurement_spec.get("deadline")
        requester_email = procurement_spec.get("requester_email", "")

        # Extract the domain from the requester email to give context to the LLM
        requester_domain = requester_email.split("@")[-1] if "@" in requester_email else ""

        logger.info(
            "Sourcing Agent invoked",
            extra={"product": product, "category": category, "requester": requester_email},
        )

        prompt = f"""
Find Tunisian suppliers for the following procurement request:

Product          : {product}
Category         : {category}
Budget max       : {f"{budget_max} TND" if budget_max else "Not specified"}
Deadline         : {deadline or "Not specified"}
Requester email  : {requester_email}
Requester domain : {requester_domain} (use this to infer the requester's industry/sector)

Search for real suppliers based in Tunisia, retrieve their contact emails,
and return up to 12 results ranked by relevance.
"""

        try:
            response = self._agent(prompt)
            raw = str(response).strip()

            # Try strict JSON parse first
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Fallback: extract JSON from markdown code block or surrounding text
                cleaned = raw
                if cleaned.startswith("```") and "```" in cleaned[3:]:
                    parts = cleaned.split("```")
                    if len(parts) > 1:
                        cleaned = parts[1].strip()
                        if cleaned.lower().startswith("json"):
                            cleaned = cleaned[4:].strip()

                candidate = _extract_first_json_object(cleaned) or _extract_first_json_object(raw)
                if not candidate:
                    raise
                data = json.loads(candidate)

        except (json.JSONDecodeError, Exception) as exc:
            logger.error("Sourcing agent failed", extra={"error": str(exc)})
            return SupplierList(
                suppliers=[],
                query_used=f"{product} {category}",
                search_timestamp=datetime.now(timezone.utc).isoformat(),
            )

        suppliers = [
            SupplierInfo(
                name=s.get("name", ""),
                website=s.get("website", ""),
                country=s.get("country", "Unknown"),
                email=s.get("email"),
                category=s.get("category", category),
                relevance_score=float(s.get("relevance_score", 0.0)),
                source_url=s.get("source_url", ""),
            )
            for s in data.get("suppliers", [])
        ]

        return SupplierList(
            suppliers=suppliers,
            query_used=data.get("query_used", f"{product} {category}"),
            search_timestamp=data.get(
                "search_timestamp",
                datetime.now(timezone.utc).isoformat(),
            ),
        )


# ═══════════════════════════════════════════════════════════════════
# STANDALONE MODE  —  python agents/agent_sourcing/agent.py
# Runs a quick test with a hardcoded procurement spec.
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    from importlib import reload

    _here = os.path.abspath(__file__)
    _root = os.path.dirname(os.path.dirname(os.path.dirname(_here)))
    _env_path = os.path.join(_root, ".env")

    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
        import config as _cfg
        reload(_cfg)
        from config import settings
    else:
        print(f"⚠️  .env not found at {_env_path}")
        import sys
        sys.exit(1)

    # Sample input: output of Agent 1 for a valid procurement request
    sample_spec = {
        "product": "wooden office desk",
        "category": "Office Supplies",
        "quantity": 1,
        "unit": "units",
        "budget_min": None,
        "budget_max": 500,
        "deadline": "2026-04-15",
        "requester_email": "test@example.com",
        "is_valid": True,
        "rejection_reason": None,
    }

    print("\n🔍  Sourcing Agent — standalone test")
    print(f"    Product  : {sample_spec['product']}")
    print(f"    Category : {sample_spec['category']}")
    print(f"    Budget   : {sample_spec['budget_max']} TND\n")

    agent = SourcingAgent()
    result = agent.source(sample_spec)

    print(f"✅  Found {len(result.suppliers)} supplier(s):\n")
    for i, s in enumerate(result.suppliers, 1):
        print(f"  [{i}] {s.name}")
        print(f"      Website : {s.website}")
        print(f"      Email   : {s.email or 'N/A'}")
        print(f"      Country : {s.country}")
        print(f"      Score   : {s.relevance_score:.2f}")
        print()

    import json as _json
    print("📄  Full JSON output:")
    print(_json.dumps(asdict(result), indent=2, ensure_ascii=False))
