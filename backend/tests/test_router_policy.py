"""Escalation policy tests.

This is the rule set the product promises operators, so it is tested as a pure
function, independent of any model behaviour.
"""

from __future__ import annotations

import pytest

from app.ai.router import _stub_decision, apply_escalation_policy
from app.models.enums import Intent, RouterAction


class TestEscalationPolicy:
    def test_high_confidence_support_is_automated(self):
        needs_human, reason = apply_escalation_policy(
            Intent.SUPPORT, 0.95, RouterAction.ANSWER
        )
        assert needs_human is False
        assert reason is None

    def test_mid_confidence_still_automated_but_reviewable(self):
        # 0.70-0.89 is "review recommended", not "block".
        needs_human, _ = apply_escalation_policy(
            Intent.PRICING, 0.78, RouterAction.ANSWER
        )
        assert needs_human is False

    def test_low_confidence_escalates(self):
        needs_human, reason = apply_escalation_policy(
            Intent.GENERAL, 0.42, RouterAction.ANSWER
        )
        assert needs_human is True
        assert "0.42" in reason

    @pytest.mark.parametrize("intent", [Intent.REFUND, Intent.COMPLAINT, Intent.UNKNOWN])
    def test_sensitive_intents_escalate_at_any_confidence(self, intent):
        # The model does not get to overrule this, even at 0.99.
        needs_human, reason = apply_escalation_policy(intent, 0.99, RouterAction.ANSWER)
        assert needs_human is True
        assert reason

    def test_model_requested_escalation_is_honoured(self):
        needs_human, _ = apply_escalation_policy(
            Intent.SUPPORT, 0.99, RouterAction.ESCALATE
        )
        assert needs_human is True

    def test_boundary_at_review_threshold(self):
        assert apply_escalation_policy(Intent.SUPPORT, 0.70, RouterAction.ANSWER)[0] is False
        assert apply_escalation_policy(Intent.SUPPORT, 0.699, RouterAction.ANSWER)[0] is True


class TestStubClassifier:
    def test_pricing_question_detected(self):
        result = _stub_decision("What are your prices for the automation package?")
        assert result["intent"] == "pricing"
        assert result["lead_score"] > 0

    def test_refund_routed_to_escalate(self):
        result = _stub_decision("I want a refund for last month")
        assert result["intent"] == "refund"
        assert result["action"] == "escalate"

    def test_purchase_intent_scores_high(self):
        result = _stub_decision("I want to sign up today")
        assert result["intent"] == "purchase_intent"
        assert result["lead_score"] >= 60

    def test_unmatched_message_is_low_confidence(self):
        result = _stub_decision("hello there")
        assert result["confidence"] < 0.70
        assert result["action"] == "escalate"

    def test_stub_is_deterministic(self):
        a = _stub_decision("how much does it cost")
        b = _stub_decision("how much does it cost")
        assert a == b
