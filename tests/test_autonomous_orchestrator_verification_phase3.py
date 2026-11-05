import pytest

from brain.orchestration.autonomous_orchestrator import AutonomousOrchestrator


class EmptyVerifier:
    async def verify(self, **kwargs):
        return {}


class StatusVerifier:
    async def verify(self, **kwargs):
        return {"status": "passed", "issues": []}


class PositiveVerifier:
    async def verify(self, **kwargs):
        return {"verified": True, "status": "passed", "issues": []}


@pytest.mark.asyncio
async def test_missing_verifier_fails_closed():
    orchestrator = AutonomousOrchestrator()
    result = await orchestrator._verify(plan={}, execution={"success": True}, goal=None)
    assert result["verified"] is False
    assert result["status"] == "not_configured"
    assert result["issues"]


@pytest.mark.asyncio
async def test_empty_verifier_result_fails_closed():
    orchestrator = AutonomousOrchestrator(verification_engine=EmptyVerifier())
    result = await orchestrator._verify(plan={}, execution={"success": True}, goal=None)
    assert result["verified"] is False
    assert result["status"] == "empty_verification"


@pytest.mark.asyncio
async def test_unknown_status_does_not_count_as_verified():
    class UnknownVerifier:
        async def verify(self, **kwargs):
            return {"status": "maybe"}

    orchestrator = AutonomousOrchestrator(verification_engine=UnknownVerifier())
    result = await orchestrator._verify(plan={}, execution={"success": True}, goal=None)
    assert result["verified"] is False


@pytest.mark.asyncio
async def test_explicit_execution_failure_overrides_positive_verifier():
    orchestrator = AutonomousOrchestrator(verification_engine=PositiveVerifier())
    result = await orchestrator._verify(plan={}, execution={"success": False}, goal=None)
    assert result["verified"] is False
    assert result["status"] == "execution_failed"
    assert any("Execution reported failure" in item for item in result["issues"])


@pytest.mark.asyncio
async def test_explicit_pass_status_is_accepted_when_execution_succeeds():
    orchestrator = AutonomousOrchestrator(verification_engine=StatusVerifier())
    result = await orchestrator._verify(plan={}, execution={"success": True}, goal=None)
    assert result["verified"] is True
    assert result["status"] == "passed"


@pytest.mark.asyncio
async def test_verifier_exception_fails_closed():
    class BrokenVerifier:
        async def verify(self, **kwargs):
            raise RuntimeError("broken")

    orchestrator = AutonomousOrchestrator(verification_engine=BrokenVerifier())
    result = await orchestrator._verify(plan={}, execution={"success": True}, goal=None)
    assert result["verified"] is False
    assert result["status"] == "error"
