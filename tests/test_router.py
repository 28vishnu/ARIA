from core.request_router import RequestRouter, Route


def test_router_greetings():
    router = RequestRouter()
    assert router.route("greeting") == Route.GREETING
    assert router.route("hello") == Route.GREETING
    assert router.route("hi") == Route.GREETING


def test_router_document_requests():
    router = RequestRouter()
    assert router.route("document") == Route.DOCUMENT
    assert router.route("search pdf") == Route.DOCUMENT


def test_router_vision_requests():
    router = RequestRouter()
    assert router.route("vision") == Route.VISION
    assert router.route("image analysis") == Route.VISION


def test_router_memory_requests():
    router = RequestRouter()
    assert router.route("memory") == Route.MEMORY
    assert router.route("search memory") == Route.MEMORY


def test_router_tool_requests():
    router = RequestRouter()
    assert router.route("tool") == Route.TOOL
    assert router.route("action") == Route.TOOL


def test_router_planning_requests():
    router = RequestRouter()
    assert router.route("plan") == Route.PLANNER
    assert router.route("task") == Route.PLANNER


def test_router_unknown_request():
    router = RequestRouter()
    assert router.route("random unrelated question") == Route.GENERAL


def test_router_handles_empty_intent():
    router = RequestRouter()
    assert router.route("") == Route.GENERAL
    assert router.route(None) == Route.GENERAL
