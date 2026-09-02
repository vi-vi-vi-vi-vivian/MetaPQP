"""Deterministic allow-list and deny-list checks for browser actions."""

from portal_audit.domain.models import SafetyProfile, TransitionDefinition


class SafetyDecisionError(RuntimeError):
    pass


class SafetyGuard:
    def authorize(
        self,
        transition: TransitionDefinition,
        profile: SafetyProfile,
        *,
        element_text: str,
        element_href: str | None,
    ) -> str:
        if transition.risk_level not in profile.allowed_risk_levels:
            raise SafetyDecisionError(
                f"risk level {transition.risk_level.value} is not allowed"
            )
        if transition.risk_level.value == "mutating":
            raise SafetyDecisionError("mutating actions are permanently prohibited")
        normalized_text = element_text.casefold()
        for term in profile.prohibited_action_terms:
            if term.casefold() in normalized_text:
                raise SafetyDecisionError(f"element text matched prohibited term: {term}")
        normalized_href = (element_href or "").casefold()
        for term in profile.prohibited_url_terms:
            if term.casefold() in normalized_href:
                raise SafetyDecisionError(f"target URL matched prohibited term: {term}")
        return (
            f"allowed transition={transition.id} risk={transition.risk_level.value} "
            f"safe_stop={transition.safe_stop}"
        )
