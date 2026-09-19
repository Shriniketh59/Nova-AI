import pytest
from app.services.token_budget_service import token_budget_service
from conftest import requires_db
from app.core.config import DEFAULT_USER_ID, DAILY_TOKEN_LIMIT


@requires_db
@pytest.mark.asyncio
async def test_token_budget_initial_allowance(app_client):
    usage = await token_budget_service.get_daily_usage(DEFAULT_USER_ID)
    assert usage["daily_limit"] == DAILY_TOKEN_LIMIT
    assert usage["remaining_tokens"] > 0
    assert not usage["is_exceeded"]

    allowed, msg = await token_budget_service.check_allowance(DEFAULT_USER_ID, estimated_tokens=100)
    assert allowed is True


@requires_db
@pytest.mark.asyncio
async def test_token_budget_record_and_persist(app_client):
    test_user_id = "11111111-2222-3333-4444-555555555555"
    initial_usage = await token_budget_service.get_daily_usage(test_user_id)
    initial_total = initial_usage["total_tokens"]

    # Record 250 prompt tokens and 150 completion tokens
    updated = await token_budget_service.record_usage(test_user_id, prompt_tokens=250, completion_tokens=150)
    assert updated["total_tokens"] == initial_total + 400
    assert updated["prompt_tokens"] >= 250
    assert updated["completion_tokens"] >= 150
    assert updated["remaining_tokens"] == DAILY_TOKEN_LIMIT - updated["total_tokens"]


@requires_db
@pytest.mark.asyncio
async def test_token_budget_exceeded_state(app_client):
    over_limit_user = "99999999-9999-9999-9999-999999999999"
    # Consume more than daily limit
    await token_budget_service.record_usage(over_limit_user, prompt_tokens=DAILY_TOKEN_LIMIT + 500, completion_tokens=0)

    usage = await token_budget_service.get_daily_usage(over_limit_user)
    assert usage["is_exceeded"] is True
    assert usage["remaining_tokens"] == 0

    allowed, msg = await token_budget_service.check_allowance(over_limit_user, estimated_tokens=10)
    assert allowed is False
    assert "Daily token limit reached" in msg
