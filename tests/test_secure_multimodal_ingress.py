import asyncio
from pathlib import Path
import pytest

from multimodal.secure_ingress import MultimodalInputError, SecureMultimodalIngress


class FakeGateway:
    def __init__(self):
        self.calls = []
    async def route(self, modality, payload, *, metadata=None):
        self.calls.append((modality, payload, metadata))
        return {"success": True, "capability": modality}


def test_text_routes_and_preserves_metadata():
    gateway = FakeGateway()
    ingress = SecureMultimodalIngress(gateway)
    result = asyncio.run(ingress.route("text", "hello", metadata={"source": "test"}))
    assert result["success"] is True
    assert gateway.calls[0] == ("text", "hello", {"source": "test"})


@pytest.mark.parametrize("modality,payload", [("image", b""), ("audio", b"")])
def test_empty_binary_payload_rejected(modality, payload):
    ingress = SecureMultimodalIngress(FakeGateway())
    with pytest.raises(MultimodalInputError, match="empty"):
        asyncio.run(ingress.route(modality, payload))


def test_binary_payload_type_and_size_are_checked():
    ingress = SecureMultimodalIngress(FakeGateway(), max_image_bytes=3)
    with pytest.raises(MultimodalInputError, match="raw bytes"):
        asyncio.run(ingress.route("image", "not bytes"))
    with pytest.raises(MultimodalInputError, match="exceeds"):
        asyncio.run(ingress.route("image", b"1234"))


def test_prompt_and_text_limits_are_checked():
    ingress = SecureMultimodalIngress(FakeGateway(), max_text_chars=3, max_prompt_chars=2)
    with pytest.raises(MultimodalInputError, match="text exceeds"):
        asyncio.run(ingress.route("text", "long"))
    with pytest.raises(MultimodalInputError, match="prompt exceeds"):
        asyncio.run(ingress.route("image", b"x", metadata={"prompt": "long"}))


def test_path_traversal_outside_configured_document_root_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    ingress = SecureMultimodalIngress(FakeGateway(), document_roots=[allowed])
    with pytest.raises(MultimodalInputError, match="outside"):
        asyncio.run(ingress.route("document", outside))


def test_document_path_must_be_under_configured_root(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    document = root / "sample.txt"
    document.write_text("hello", encoding="utf-8")
    gateway = FakeGateway()
    ingress = SecureMultimodalIngress(gateway, document_roots=[root])
    result = asyncio.run(ingress.route("document", document))
    assert result["success"] is True
    assert gateway.calls[0][1] == str(document.resolve())


def test_computer_control_disabled_by_default():
    gateway = FakeGateway()
    ingress = SecureMultimodalIngress(gateway)
    result = asyncio.run(ingress.route("computer", "click this"))
    assert result["blocked"] is True
    assert gateway.calls == []


def test_unknown_modality_rejected():
    ingress = SecureMultimodalIngress(FakeGateway())
    with pytest.raises(MultimodalInputError, match="unsupported"):
        asyncio.run(ingress.route("telepathy", "hello"))
