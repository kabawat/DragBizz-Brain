from app.prompts.abuse import (
    _FIRM_LINES,
    abuse_tone_rule,
    contains_abuse,
    count_abuse_strikes,
)
from app.prompts.system.chat import build_chat_system_prompt


def test_detects_common_gaali_not_sale() -> None:
    assert contains_abuse("abe chutiya sale bata")
    assert contains_abuse("fuck you")
    assert not contains_abuse("aaj ki sale kitni hai")
    assert not contains_abuse("vikram ka khata")


def test_strikes_count_across_session() -> None:
    prior = ["hi", "madarchod", "sale bata"]
    assert count_abuse_strikes(prior, "ok") == 1
    assert count_abuse_strikes(prior, "bc kya bakwas") == 2
    assert count_abuse_strikes(["mc", "bhenchod"], "chutiya") == 3


def test_firm_lines_rotate_and_prompt_varies() -> None:
    assert len(_FIRM_LINES) >= 5
    firm3 = abuse_tone_rule(3)
    firm4 = abuse_tone_rule(4)
    assert "dhandhe" in firm3.lower() or "dukaan" in firm3.lower()
    assert "Suggested this turn" in firm3
    assert firm3 != firm4
    assert _FIRM_LINES[0] in firm3
    assert _FIRM_LINES[1] in firm4

    prompt = build_chat_system_prompt(
        language="hi",
        store_id="a" * 24,
        tools=[],
        routing="neither",
        abuse_strikes=3,
    )
    assert "sparingly" in prompt.lower() or "rarely" in prompt.lower()
    assert "emoji" in prompt.lower()
    assert "dhandhe" in prompt.lower() or "dukaan" in prompt.lower()
