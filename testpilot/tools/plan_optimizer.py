"""Conservative plan deduplication: explicit inputs, setup and expected behavior must match."""

from testpilot.schemas.test_plan import TestPlan


def optimize_plan(plan: TestPlan) -> tuple[TestPlan, list[str]]:
    result = plan.model_copy(deep=True)
    kept = {}
    notes = []
    for case in result.cases:
        # Preserve case/literal whitespace inside descriptions of input values: no NLP guessing.
        key = tuple(
            value.strip()
            for value in (
                case.target_symbol,
                case.setup,
                case.input_strategy,
                case.expected_behavior,
            )
        )
        if key not in kept:
            kept[key] = case
            continue
        previous = kept[key]
        previous.additional_categories = sorted(
            (
                set(previous.additional_categories)
                | set(case.additional_categories)
                | {case.category}
            )
            - {previous.category}
        )
        previous.priority = min(previous.priority, case.priority)
        notes.append(f"Plan deduplicated: {plan.target}: {case.target_symbol} ({case.category})")
    result.cases = list(kept.values())
    return result, notes
