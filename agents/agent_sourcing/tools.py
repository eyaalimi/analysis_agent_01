"""
agents/agent_sourcing/tools.py
Tools used by the Sourcing Agent — Tavily search + email scraping.
"""
import json
import re
from typing import Optional

import requests
from strands import tool

from config import settings
from logger import get_logger

logger = get_logger(__name__)

# ── Email extraction helpers ─────────────────────────────────────────────────

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SKIP_PREFIXES = ("noreply", "no-reply", "example", "test", "donotreply", "webmaster", "info@example")

# Common contact page paths to try when scraping a supplier's website
_CONTACT_PATHS = [
    "/contact", "/contact-us", "/contactez-nous",
    "/nous-contacter", "/contact.html", "/about", "/a-propos",
]


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


# ── Strands @tool functions ──────────────────────────────────────────────────

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

    query = f"{product} fournisseur Tunisie supplier Tunisia {category}"
    logger.info("Searching Tunisian suppliers via Tavily", extra={"query": query})

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "exclude_domains": ["amazon.com", "ebay.com", "alibaba.com", "aliexpress.com"],
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

        simplified = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:400],
                "score": round(r.get("score", 0.0), 3),
            }
            for r in data.get("results", [])
        ]
        return json.dumps(simplified, ensure_ascii=False)

    except requests.RequestException as exc:
        logger.error("Tavily search failed", extra={"error": str(exc)})
        return json.dumps([])


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
