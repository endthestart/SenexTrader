"""Tests for suggestion email builder."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from services.notifications.email.suggestion_email_builder import SuggestionEmailBuilder


class TestSuggestionEmailBuilder:
    """Test SuggestionEmailBuilder class."""

    @pytest.fixture
    def builder(self):
        """Create email builder for testing."""
        return SuggestionEmailBuilder(base_url="https://test.example.com")

    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = Mock()
        user.email = "test@example.com"
        return user

    @pytest.fixture
    def mock_suggestion(self):
        """Create mock trading suggestion."""
        suggestion = Mock()
        suggestion.id = 123
        suggestion.underlying_symbol = "SPY"
        suggestion.expiration_date = date(2025, 11, 21)
        suggestion.short_put_strike = Decimal("450.00")
        suggestion.long_put_strike = Decimal("445.00")
        suggestion.put_spread_quantity = 1
        suggestion.short_call_strike = None
        suggestion.long_call_strike = None
        suggestion.call_spread_quantity = 0
        suggestion.total_mid_credit = Decimal("1.50")
        suggestion.total_credit = Decimal("1.40")
        suggestion.max_risk = Decimal("350.00")
        return suggestion

    # Helper method tests
    def test_get_confidence_high(self, builder):
        """Test high confidence threshold."""
        assert builder.get_confidence(85) == "HIGH"
        assert builder.get_confidence(70) == "HIGH"

    def test_get_confidence_medium(self, builder):
        """Test medium confidence threshold."""
        assert builder.get_confidence(65) == "MEDIUM"
        assert builder.get_confidence(50) == "MEDIUM"

    def test_get_confidence_low(self, builder):
        """Test low confidence threshold."""
        assert builder.get_confidence(45) == "LOW"
        assert builder.get_confidence(0) == "LOW"

    def test_format_strategy_name(self, builder):
        """Test strategy name formatting."""
        assert builder.format_strategy_name("bull_put_spread") == "Bull Put Spread"
        assert builder.format_strategy_name("senex_trident") == "Senex Trident"
        assert builder.format_strategy_name("short_iron_condor") == "Short Iron Condor"

    # Multi-symbol email tests
    def test_multi_symbol_email_no_candidates(self, builder, mock_user):
        """Test multi-symbol email with no candidates."""
        subject, body = builder.build_multi_symbol_email(user=mock_user, candidates=[])

        assert "No Suitable Trades Today" in subject
        assert "NO SUITABLE TRADES TODAY" in body
        assert "Market conditions did not meet criteria" in body
        assert "https://test.example.com/trading/" in body

    def test_multi_symbol_email_one_candidate(self, builder, mock_user, mock_suggestion):
        """Test multi-symbol email with single candidate."""
        candidates = [
            {
                "symbol": "SPY",
                "strategy_name": "bull_put_spread",
                "suggestion": mock_suggestion,
                "score": 75.5,
                "market_report": {"iv_rank": 45, "market_stress_level": 35},
            }
        ]

        subject, body = builder.build_multi_symbol_email(user=mock_user, candidates=candidates)

        assert "SPY Top Pick - HIGH" in subject
        assert "🥇 SPY - Bull Put Spread" in body
        assert "Score: 75.5/100 - HIGH CONFIDENCE" in body
        assert "Put Spread: $450.00/$445.00" in body
        assert "Expected Credit: $1.50" in body
        assert "Max Risk: $350.00" in body
        assert "IV Rank: 45%" in body
        assert "Execute: https://test.example.com/trading/?suggestion=123" in body

    def test_multi_symbol_email_three_candidates(self, builder, mock_user, mock_suggestion):
        """Test multi-symbol email with top 3 candidates."""
        candidates = [
            {
                "symbol": "SPY",
                "strategy_name": "bull_put_spread",
                "suggestion": mock_suggestion,
                "score": 75.5,
                "market_report": {},
            },
            {
                "symbol": "QQQ",
                "strategy_name": "bear_call_spread",
                "suggestion": mock_suggestion,
                "score": 65.0,
                "market_report": {},
            },
            {
                "symbol": "IWM",
                "strategy_name": "senex_trident",
                "suggestion": mock_suggestion,
                "score": 55.5,
                "market_report": {},
            },
        ]

        subject, body = builder.build_multi_symbol_email(user=mock_user, candidates=candidates)

        assert "3 Opportunities" in subject
        assert "🥇 SPY" in body
        assert "🥈 QQQ" in body
        assert "🥉 IWM" in body
        assert "Bear Call Spread" in body
        assert "Senex Trident" in body

    def test_multi_symbol_email_with_others(self, builder, mock_user, mock_suggestion):
        """Test multi-symbol email with top 3 + others section."""
        candidates = []
        for i, symbol in enumerate(["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD"]):
            candidates.append(
                {
                    "symbol": symbol,
                    "strategy_name": "bull_put_spread",
                    "suggestion": mock_suggestion,
                    "score": 70 - i * 5,
                    "market_report": {},
                }
            )

        subject, body = builder.build_multi_symbol_email(user=mock_user, candidates=candidates)

        assert "TOP OPPORTUNITIES (3)" in body
        assert "OTHER OPPORTUNITIES (3)" in body
        assert "Symbol" in body  # Table header
        assert "Strategy" in body
        assert "DIA" in body  # 4th candidate should be in others
        assert "TLT" in body  # 5th candidate should be in others

    def test_multi_symbol_email_confidence_levels(self, builder, mock_user, mock_suggestion):
        """Test confidence levels in multi-symbol email."""
        candidates = [
            {
                "symbol": "HIGH",
                "strategy_name": "strategy_1",
                "suggestion": mock_suggestion,
                "score": 80,
                "market_report": {},
            },
            {
                "symbol": "MED",
                "strategy_name": "strategy_2",
                "suggestion": mock_suggestion,
                "score": 60,
                "market_report": {},
            },
            {
                "symbol": "LOW",
                "strategy_name": "strategy_3",
                "suggestion": mock_suggestion,
                "score": 40,
                "market_report": {},
            },
        ]

        subject, body = builder.build_multi_symbol_email(user=mock_user, candidates=candidates)

        assert "HIGH CONFIDENCE" in body
        assert "MEDIUM CONFIDENCE" in body
        assert "LOW CONFIDENCE" in body

    # Single-symbol email tests
    def test_single_symbol_email_no_suggestions(self, builder, mock_user):
        """Test single-symbol email with no suggestions (hard stops)."""
        global_context = {
            "type": "hard_stops",
            "reasons": ["MARKET_HALT", "EXTREME_VOLATILITY"],
        }

        subject, body = builder.build_single_symbol_email(
            user=mock_user, suggestions_list=[], global_context=global_context
        )

        assert "No Suitable Trade Today" in subject
        assert "NO TRADE RECOMMENDED TODAY" in body
        assert "hard stops" in body
        assert "MARKET_HALT" in body
        assert "EXTREME_VOLATILITY" in body

    def test_single_symbol_email_low_scores(self, builder, mock_user):
        """Test single-symbol email with low scores."""
        global_context = {
            "type": "low_scores",
            "best_score": 25.5,
            "all_scores": {
                "bull_put_spread": {"score": 25.5},
                "bear_call_spread": {"score": 20.0},
            },
        }

        subject, body = builder.build_single_symbol_email(
            user=mock_user, suggestions_list=[], global_context=global_context
        )

        assert "No Suitable Trade Today" in subject
        assert "below threshold (best: 25.5)" in body
        assert "Bull Put Spread: 25.5" in body
        assert "Bear Call Spread: 20.0" in body

    def test_single_symbol_email_with_suggestions(
        self, builder, mock_user, mock_suggestion, monkeypatch
    ):
        """Test single-symbol email with suggestions."""
        # Mock the ExplanationBuilder to return formatted snapshot
        from unittest.mock import MagicMock

        mock_explanation_builder = MagicMock()
        mock_explanation_builder.explain_market_snapshot.return_value = {
            "price": "$450.50",
            "change": "+$2.50 (+0.6%)",
            "iv_rank": "45% (Moderate)",
            "trend": "Neutral/Sideways",
            "stress": "30/100 (Low)",
            "range_bound": "Yes",
        }
        # Patch it in the module where it's imported (services.utils.explanation_builder)
        monkeypatch.setattr(
            "services.utils.explanation_builder.ExplanationBuilder", mock_explanation_builder
        )

        suggestions_list = [
            ("bull_put_spread", mock_suggestion, "Bullish market"),
            ("bear_call_spread", mock_suggestion, "Neutral market"),
        ]
        global_context = {
            "market_report": Mock(),  # Mock object instead of dict
            "all_scores": {
                "bull_put_spread": {"score": 75.0},
                "bear_call_spread": {"score": 65.0},
            },
        }

        subject, body = builder.build_single_symbol_email(
            user=mock_user, suggestions_list=suggestions_list, global_context=global_context
        )

        assert "2 Trades" in subject
        assert "Bull Put Spread Top Pick" in subject
        assert "MARKET SNAPSHOT" in body
        assert "SPY" in body
        assert "IV Rank" in body
        assert "🥇 STRATEGY #1: BULL PUT SPREAD" in body
        assert "🥈 STRATEGY #2: BEAR CALL SPREAD" in body
        assert "75.0/100 - HIGH CONFIDENCE" in body
        assert "65.0/100 - MEDIUM CONFIDENCE" in body

    def test_single_symbol_email_medal_assignment(self, builder, mock_user, mock_suggestion):
        """Test medal assignment in single-symbol email."""
        suggestions_list = [
            (f"strategy_{i}", mock_suggestion, f"Explanation {i}") for i in range(5)
        ]
        global_context = {"all_scores": {f"strategy_{i}": {"score": 70 - i * 5} for i in range(5)}}

        subject, body = builder.build_single_symbol_email(
            user=mock_user, suggestions_list=suggestions_list, global_context=global_context
        )

        assert "🥇" in body  # 1st place
        assert "🥈" in body  # 2nd place
        assert "🥉" in body  # 3rd place
        assert "#4" in body  # 4th place
        assert "#5" in body  # 5th place

    def test_multi_symbol_quantity_display(self, builder, mock_user):
        """Test quantity display for multiple contracts."""
        suggestion = Mock()
        suggestion.id = 123
        suggestion.underlying_symbol = "SPY"
        suggestion.expiration_date = date(2025, 11, 21)
        suggestion.short_put_strike = Decimal("450.00")
        suggestion.long_put_strike = Decimal("445.00")
        suggestion.put_spread_quantity = 3  # Multiple contracts
        suggestion.short_call_strike = None
        suggestion.long_call_strike = None
        suggestion.total_mid_credit = Decimal("1.50")
        suggestion.total_credit = Decimal("1.40")
        suggestion.max_risk = Decimal("350.00")

        candidates = [
            {
                "symbol": "SPY",
                "strategy_name": "bull_put_spread",
                "suggestion": suggestion,
                "score": 75.5,
                "market_report": {},
            }
        ]

        subject, body = builder.build_multi_symbol_email(user=mock_user, candidates=candidates)

        assert "Put Spread: $450.00/$445.00 (x3)" in body
