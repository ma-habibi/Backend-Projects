import pytest


@pytest.fixture(autouse=True)
def app_env(monkeypatch):
    """
    Ensure the environment variables Auth and ImageProcessingService.login
    read via os.getenv are always present during tests, regardless of
    whether a local .env file exists.
    """
    monkeypatch.setenv("APP_JWT_SECRET", "4kYkfCyepWTQgD95FcKRd942nGdpyttpC4P3vget-xZj7s6V6aFCNkTAtsKMJeGXlbwBkqfxBoxlvV62l2c7vA")
    monkeypatch.setenv("APP_JWT_TOKEN_EXPIRATION_MINUTES", "15")
