import pytest
from app.auth import TokenManager


@pytest.fixture(autouse=True)
def reset_token_manager_store():
    TokenManager.reset_store()
    yield
    TokenManager.reset_store()
