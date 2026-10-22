from citymate.config import Settings


def test_model_switch_controls_configured_key(monkeypatch):
    # dotenv may populate the key even when Windows PowerShell removes an empty
    # environment variable. The explicit switch must still keep rules mode on.
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("CITYMATE_MODEL_ENABLED", "false")
    assert Settings().api_key == ""
    monkeypatch.setenv("CITYMATE_MODEL_ENABLED", "true")
    assert Settings().api_key == "test-only-not-a-real-key"
