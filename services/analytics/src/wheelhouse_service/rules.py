"""Opt-in rule switches O1-O6 on top of the original v1 rules, and the views each one changes."""

from typing import Literal, get_args

Rule = Literal["O1", "O2", "O3", "O4", "O5", "O6"]
Rules = frozenset[Rule]
View = Literal["cycle", "levels", "costbasis", "pressure", "sellside", "agecohorts", "perps"]

ALL_RULES: Rules = frozenset(get_args(Rule))
# The rules implemented for each view so far. A rule only reaches a payload, and its label, once it
# is implemented for that view.
IMPLEMENTED: dict[View, Rules] = {
    **{view: frozenset() for view in get_args(View)},
    "cycle": frozenset({"O1", "O4"}),
    "levels": frozenset({"O1", "O5"}),
    "costbasis": frozenset({"O1", "O5"}),
    "pressure": frozenset({"O1", "O2", "O3"}),
    "perps": frozenset({"O1", "O6"}),
}
_BY_CODE: dict[str, Rule] = {rule: rule for rule in ALL_RULES}
_V1 = "V1"


def parse_rules(text: str | None) -> Rules:
    """WHEELHOUSE_RULES: comma-separated codes O1-O6, in any case, with blanks and repeats ignored.

    Unset or empty means every rule: compose files easily produce an empty value, which must not
    turn them all off. `v1` alone turns every rule off. Anything else raises ValueError, an empty
    item included: a stray comma is a mistake, never a rule.
    """
    if text is None or not text.strip():
        return ALL_RULES
    codes = {code.strip().upper() for code in text.split(",")}
    if "" in codes:
        raise ValueError("the list has an empty item; remove the extra comma")
    if _V1 in codes:
        if len(codes) > 1:
            raise ValueError("v1 turns every rule off and cannot be combined with other rules")
        return frozenset()
    unknown = sorted(code for code in codes if code not in _BY_CODE)
    if unknown:
        raise ValueError(f"Unknown rule {unknown[0]!r}: use O1-O6, or v1 alone")
    return frozenset(_BY_CODE[code] for code in codes)


def rules_for_view(view: View, rules: Rules) -> list[Rule]:
    """The rules that are on and implemented for `view`, in order: what its payload records."""
    return sorted(rules & IMPLEMENTED[view])
