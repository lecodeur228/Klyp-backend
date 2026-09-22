"""Unit tests for core exceptions and prompts."""

from app.ai.prompts.registry import get_prompt, render_prompt
from app.ai.providers.fake import FakeAIProvider
from app.core.constants import ErrorCode
from app.core.exceptions import AITimeoutException, AuthenticationException


def test_error_codes_stable() -> None:
    assert ErrorCode.VALIDATION_ERROR.value == "VALIDATION_ERROR"
    assert ErrorCode.AI_TIMEOUT.value == "AI_TIMEOUT"
    assert ErrorCode.JOB_FAILED.value == "JOB_FAILED"
    assert ErrorCode.UPLOAD_FAILED.value == "UPLOAD_FAILED"
    assert ErrorCode.EDIT_PLAN_INVALID.value == "EDIT_PLAN_INVALID"
    assert ErrorCode.RENDER_FAILED.value == "RENDER_FAILED"


def test_authentication_exception_status() -> None:
    exc = AuthenticationException()
    assert exc.status_code == 401
    assert exc.code == ErrorCode.UNAUTHENTICATED


def test_ai_timeout_exception() -> None:
    exc = AITimeoutException()
    assert exc.status_code == 504


def test_prompt_registry() -> None:
    prompt = get_prompt("summarize")
    assert prompt.version == "1.0.0"
    system, user, version = render_prompt("summarize", content="Hello world")
    assert "summarizes" in system.lower() or "concise" in system.lower()
    assert "Hello world" in user
    assert version == "1.0.0"
    edit = get_prompt("edit_plan")
    assert edit.version == "1.0.0"
    _, edit_user, _ = render_prompt(
        "edit_plan",
        prompt="cut silence",
        duration="10",
        transcript="hi",
        vad="[]",
        source_video_id="v1",
    )
    assert "cut silence" in edit_user


async def test_fake_provider_generate() -> None:
    provider = FakeAIProvider()
    result = await provider.generate(messages=[{"role": "user", "content": "ping"}])
    assert result.provider == "fake"
    assert "ping" in result.content
