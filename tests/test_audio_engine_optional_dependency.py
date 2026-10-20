import asyncio

import audio_engine
from audio_engine import AudioEngine


def test_audio_engine_module_imports_without_genai_sdk(monkeypatch):
    monkeypatch.setattr(audio_engine, "_genai", None)
    engine = AudioEngine(api_key="test-key")
    assert engine.client is None
    result = asyncio.run(engine.transcribe_audio(b"some audio bytes"))
    assert result["success"] is False
    assert result["transcript"] == ""
    assert "google-genai" in result["summary"]


def test_audio_engine_without_api_key_is_offline(monkeypatch):
    monkeypatch.setattr(audio_engine, "_genai", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    engine = AudioEngine()
    result = asyncio.run(engine.transcribe_audio(b"some audio bytes"))
    assert result["success"] is False
    assert result["language"] == "unknown"


def test_empty_audio_is_rejected():
    engine = AudioEngine()
    result = asyncio.run(engine.transcribe_audio(b""))
    assert result["success"] is False
    assert result["duration_seconds"] == 0
    assert "No audio data" in result["summary"]
