"""
tests/test_agent_evaluation.py
Unit tests for the Evaluation Agent (Agent 5).

Pure algorithmic — no LLM, no external dependencies.
Run with: pytest tests/test_agent_evaluation.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from agents.agent_evaluation.agent import (
    EvaluationAgent,
    EvaluationResult,
    _score_price,
    _score_delivery,
    _parse_warranty_months,
    _score_warranty,
    _parse_payment_days,
    _score_payment,
    _score_budget_fit,
    _generate_recommendation,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def spec():
    return {
        "product": "ergonomic office chairs",
        "quantity": 10,
        "budget_max": 5000,
        "currency": "TND",
        "deadline": "2026-04-30",
    }


@pytest.fixture
def two_offers():
    return [
        {
            "supplier_name": "SupplierA",
            "supplier_email": "a@supplier.com",
            "unit_price": 400.0,
            "total_price": 4000.0,
            "currency": "TND",
            "delivery_days": 10,
            "warranty": "2 years",
            "payment_terms": "30 days net",
        },
        {
            "supplier_name": "SupplierB",
            "supplier_email": "b@supplier.com",
            "unit_price": 500.0,
            "total_price": 5000.0,
            "currency": "TND",
            "delivery_days": 7,
            "warranty": "1 year",
            "payment_terms": "60 days net",
        },
    ]


@pytest.fixture
def three_offers(two_offers):
    return two_offers + [
        {
            "supplier_name": "SupplierC",
            "supplier_email": "c@supplier.com",
            "unit_price": 450.0,
            "total_price": 4500.0,
            "currency": "TND",
            "delivery_days": 14,
            "warranty": "6 months",
            "payment_terms": "15 days net",
        },
    ]


# ── Price scoring ───────────────────────────────────────────────────────────

class TestScorePrice:

    def test_lowest_gets_100(self):
        prices = [4000.0, 5000.0, 6000.0]
        assert _score_price(prices, 0) == 100.0

    def test_higher_price_gets_lower_score(self):
        prices = [4000.0, 5000.0]
        score = _score_price(prices, 1)
        assert score == 80.0  # 4000/5000 * 100

    def test_none_price_returns_zero(self):
        prices = [4000.0, None]
        assert _score_price(prices, 1) == 0.0

    def test_all_none_returns_zero(self):
        prices = [None, None]
        assert _score_price(prices, 0) == 0.0


# ── Delivery scoring ───────────────────────────────────────────────────────

class TestScoreDelivery:

    def test_fastest_gets_100(self):
        days = [7, 10, 14]
        assert _score_delivery(days, 0) == 100.0

    def test_slower_gets_lower_score(self):
        days = [7, 14]
        assert _score_delivery(days, 1) == 50.0  # 7/14 * 100

    def test_none_days_returns_zero(self):
        days = [7, None]
        assert _score_delivery(days, 1) == 0.0


# ── Warranty parsing and scoring ────────────────────────────────────────────

class TestParseWarranty:

    def test_years(self):
        assert _parse_warranty_months("2 years") == 24

    def test_months(self):
        assert _parse_warranty_months("6 months") == 6

    def test_french_mois(self):
        assert _parse_warranty_months("12 mois") == 12

    def test_french_ans(self):
        assert _parse_warranty_months("2 ans") == 24

    def test_none(self):
        assert _parse_warranty_months(None) == 0

    def test_empty(self):
        assert _parse_warranty_months("") == 0


class TestScoreWarranty:

    def test_longest_gets_100(self):
        warranties = ["2 years", "1 year", "6 months"]
        assert _score_warranty(warranties, 0) == 100.0

    def test_shorter_gets_lower(self):
        warranties = ["2 years", "1 year"]
        assert _score_warranty(warranties, 1) == 50.0  # 12/24


# ── Payment parsing and scoring ─────────────────────────────────────────────

class TestParsePayment:

    def test_days_net(self):
        assert _parse_payment_days("30 days net") == 30

    def test_french_jours(self):
        assert _parse_payment_days("60 jours") == 60

    def test_none(self):
        assert _parse_payment_days(None) == 0


class TestScorePayment:

    def test_longest_gets_100(self):
        terms = ["60 days net", "30 days net"]
        assert _score_payment(terms, 0) == 100.0

    def test_shorter_gets_lower(self):
        terms = ["60 days net", "30 days net"]
        assert _score_payment(terms, 1) == 50.0


# ── Budget fit scoring ──────────────────────────────────────────────────────

class TestBudgetFit:

    def test_under_budget_high_score(self):
        score = _score_budget_fit(3000, 5000)
        assert score >= 70.0

    def test_at_budget_gets_70(self):
        score = _score_budget_fit(5000, 5000)
        assert score == 70.0

    def test_over_budget_penalized(self):
        score = _score_budget_fit(7000, 5000)
        assert score < 70.0

    def test_unknown_budget_returns_neutral(self):
        assert _score_budget_fit(4000, None) == 50.0

    def test_unknown_price_returns_neutral(self):
        assert _score_budget_fit(None, 5000) == 50.0


# ── Recommendation ──────────────────────────────────────────────────────────

class TestRecommendation:

    def test_rank_1_best_value(self):
        score = MagicMock(price_score=95, delivery_score=95)
        rec = _generate_recommendation(score, 1, 3)
        assert "Best overall value" in rec

    def test_last_rank(self):
        score = MagicMock(price_score=50, delivery_score=50)
        rec = _generate_recommendation(score, 3, 3)
        assert "Least competitive" in rec

    def test_middle_rank_with_strengths(self):
        score = MagicMock(price_score=85, delivery_score=85, warranty_score=60)
        rec = _generate_recommendation(score, 2, 3)
        assert "Good option" in rec


# ── EvaluationAgent.evaluate() ──────────────────────────────────────────────

class TestEvaluateAgent:

    @patch("agents.agent_evaluation.tools.generate_pdf_report", return_value="/tmp/report.pdf")
    def test_returns_evaluation_result(self, mock_pdf, spec, two_offers):
        agent = EvaluationAgent()
        result = agent.evaluate(two_offers, spec, generate_pdf=False)
        assert isinstance(result, EvaluationResult)
        assert result.request_product == "ergonomic office chairs"
        assert len(result.scores) == 2

    @patch("agents.agent_evaluation.tools.generate_pdf_report", return_value="/tmp/report.pdf")
    def test_ranks_are_assigned(self, mock_pdf, spec, two_offers):
        agent = EvaluationAgent()
        result = agent.evaluate(two_offers, spec, generate_pdf=False)
        ranks = [s.rank for s in result.scores]
        assert sorted(ranks) == [1, 2]

    @patch("agents.agent_evaluation.tools.generate_pdf_report", return_value="/tmp/report.pdf")
    def test_best_offer_is_rank_1(self, mock_pdf, spec, two_offers):
        agent = EvaluationAgent()
        result = agent.evaluate(two_offers, spec, generate_pdf=False)
        assert result.best_offer == result.scores[0].supplier_name

    def test_empty_offers(self, spec):
        agent = EvaluationAgent()
        result = agent.evaluate([], spec, generate_pdf=False)
        assert result.scores == []
        assert result.best_offer is None

    @patch("agents.agent_evaluation.tools.generate_pdf_report", return_value="/tmp/report.pdf")
    def test_three_offers_ranking(self, mock_pdf, spec, three_offers):
        agent = EvaluationAgent()
        result = agent.evaluate(three_offers, spec, generate_pdf=False)
        assert len(result.scores) == 3
        # Scores should be descending
        scores = [s.overall_score for s in result.scores]
        assert scores == sorted(scores, reverse=True)

    @patch("agents.agent_evaluation.tools.generate_pdf_report", return_value="/tmp/report.pdf")
    def test_overall_score_range(self, mock_pdf, spec, two_offers):
        agent = EvaluationAgent()
        result = agent.evaluate(two_offers, spec, generate_pdf=False)
        for s in result.scores:
            assert 0 <= s.overall_score <= 100

    @patch("agents.agent_evaluation.tools.generate_pdf_report", return_value="/tmp/report.pdf")
    def test_pdf_generation_called(self, mock_pdf, spec, two_offers):
        agent = EvaluationAgent()
        result = agent.evaluate(two_offers, spec, generate_pdf=True)
        mock_pdf.assert_called_once()
        assert result.report_path == "/tmp/report.pdf"


# ── PDF / text report generation ────────────────────────────────────────────

class TestReportGeneration:

    def test_text_fallback(self, spec, two_offers, tmp_path):
        """When reportlab is unavailable, a .txt report is generated."""
        agent = EvaluationAgent()
        result = agent.evaluate(two_offers, spec, generate_pdf=True, output_dir=str(tmp_path))
        # Result should be a file path (either .pdf or .txt)
        assert result.report_path is not None
        assert Path(result.report_path).exists()

    def test_text_report_content(self, spec, two_offers, tmp_path):
        """Text report contains supplier names and scores."""
        from agents.agent_evaluation.tools import _generate_text_report
        from agents.agent_evaluation.agent import EvaluationAgent

        agent = EvaluationAgent()
        eval_result = agent.evaluate(two_offers, spec, generate_pdf=False)

        report_path = tmp_path / "test_report.txt"
        _generate_text_report(report_path, "office chairs", spec, eval_result.scores)

        content = report_path.read_text()
        assert "SupplierA" in content
        assert "SupplierB" in content
        assert "SUPPLIER EVALUATION REPORT" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
