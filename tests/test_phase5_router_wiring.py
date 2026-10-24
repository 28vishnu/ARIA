from fastapi.testclient import TestClient
import main


def test_workspace_routes_are_registered():
    paths = {route.path for route in main.app.routes}
    expected = {
        "/workspace/overview", "/workspace/projects", "/workspace/notes",
        "/workspace/tasks", "/workspace/workflows", "/workspace/workflows/{workflow_id}/run",
        "/workspace/workflow-runs", "/workspace/research-reports",
    }
    assert expected.issubset(paths)


def test_workspace_routes_require_owner_session():
    client = TestClient(main.app)
    for path in ("/workspace/overview", "/workspace/projects", "/workspace/notes", "/workspace/tasks", "/workspace/workflows", "/workspace/research-reports"):
        response = client.get(path)
        assert response.status_code == 401, path
