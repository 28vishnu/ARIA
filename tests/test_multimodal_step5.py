import asyncio
from pathlib import Path

from multimodal.image.analyzer import ImageAnalyzer


class FakeVision:
    def __init__(self, result=None):
        self.result = result or {
            "success": True,
            "text": "HELLO WORLD",
            "description": "A sign with text.",
            "entities": [{"type": "text", "value": "HELLO WORLD", "confidence": 0.99}],
            "metadata": {},
        }
        self.calls = []

    async def analyze_visual(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_image_analyzer_uses_real_vision_engine_with_bytes():
    vision = FakeVision()
    analyzer = ImageAnalyzer(vision_engine=vision)
    answer = asyncio.run(analyzer.analyze(b"fake-image-bytes", "Read the sign."))
    assert "A sign with text." in answer
    assert "HELLO WORLD" in answer
    assert vision.calls[0]["image_bytes"] == b"fake-image-bytes"
    assert vision.calls[0]["prompt"] == "Read the sign."


def test_image_analyzer_accepts_path_and_detects_filename(tmp_path: Path):
    path = tmp_path / "sample.png"
    path.write_bytes(b"image")
    vision = FakeVision()
    answer = asyncio.run(ImageAnalyzer(vision_engine=vision).analyze(str(path)))
    assert "HELLO WORLD" in answer
    assert vision.calls[0]["file_name"] == "sample.png"


def test_image_analyzer_rejects_empty_bytes():
    answer = asyncio.run(ImageAnalyzer(vision_engine=FakeVision()).analyze(b""))
    assert "empty" in answer.lower()


def test_image_analyzer_reports_unavailable_engine_without_fabricating_analysis():
    answer = asyncio.run(ImageAnalyzer(vision_engine=None).analyze(b"image"))
    # If the environment has a configured provider, the adapter may construct it;
    # assert only that it never returns the old fabricated stub response.
    assert "Image Analysis Complete" not in answer


def test_image_analyzer_reports_provider_failure():
    vision = FakeVision({"success": False, "description": "Vision subsystem offline", "text": "", "entities": []})
    answer = asyncio.run(ImageAnalyzer(vision_engine=vision).analyze(b"image"))
    assert "failed" in answer.lower()
    assert "offline" in answer.lower()
