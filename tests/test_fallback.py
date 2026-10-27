from app.prompts.fallback import (
    get_confirmation_review_message,
    get_fallback_message,
)


def test_pending_confirmation_copy_is_actionable_in_supported_languages() -> None:
    assert "confirm" in get_confirmation_review_message("en").lower()
    assert "cancel" in get_confirmation_review_message("en").lower()
    assert "confirm" in get_confirmation_review_message("hi-IN").lower()
    assert "cancel" in get_confirmation_review_message("hi-IN").lower()
    assert "confirm" in get_confirmation_review_message("gu-IN").lower()
    assert "cancel" in get_confirmation_review_message("gu-IN").lower()


def test_pending_confirmation_copy_does_not_use_store_data_failure_fallback() -> None:
    assert get_confirmation_review_message("en") != get_fallback_message("en")

