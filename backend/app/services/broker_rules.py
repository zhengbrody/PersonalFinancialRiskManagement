"""Versioned broker buying-power / margin rule interface.

The ONLY built-in provider is ``unknown``: every requirement it is asked for is
returned as unknown with a reason. No Reg-T, portfolio-margin or house rule is
encoded anywhere in this module, because none has been verified for any
account. A future provider must carry its own id, effective-dated version and
source, and be added deliberately (with tests) — never inferred.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from ..core.responses import APIError

Requirement = Literal["buying_power_impact", "maintenance_requirement", "uncovered_call_collateral"]


@dataclass(frozen=True)
class RuleAnswer:
    requirement: Requirement
    status: Literal["unknown"]
    value: None
    reason: str


class BrokerRuleProvider(Protocol):
    provider_id: str
    rule_version: str
    source: str

    def evaluate(self, requirement: Requirement) -> RuleAnswer: ...


@dataclass(frozen=True)
class UnknownBrokerRules:
    provider_id: str = "unknown"
    rule_version: str = "none"
    source: str = "No verified broker rule set is connected for this account."

    def evaluate(self, requirement: Requirement) -> RuleAnswer:
        return RuleAnswer(
            requirement=requirement,
            status="unknown",
            value=None,
            reason=(
                "Broker buying power, maintenance and collateral rules are not verified; "
                "this requirement is unknown and must not be assumed to be zero or satisfied."
            ),
        )


_PROVIDERS: dict[str, BrokerRuleProvider] = {"unknown": UnknownBrokerRules()}


def provider(provider_id: str = "unknown") -> BrokerRuleProvider:
    try:
        return _PROVIDERS[provider_id]
    except KeyError:
        raise APIError(
            422, "broker_rules_unavailable", "Only the 'unknown' broker rule provider exists."
        ) from None
