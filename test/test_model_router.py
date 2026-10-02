from core import model_router


def test_chain_uses_gemini_then_glm(monkeypatch):
    calls = []
    monkeypatch.setattr(model_router, "_credential", lambda kind: ("http://local", "key"))

    def fake(kind, model, messages):
        calls.append(kind)
        if kind == "gemini":
            raise RuntimeError("down")
        return {"ok": True, "provider": kind, "model": model, "text": "ok"}

    monkeypatch.setattr(model_router, "_provider", fake)
    result = model_router.complete("health")
    assert result["ok"] and result["provider"] == "glm"
    assert calls == ["gemini", "glm"]


def test_status_exposes_three_roles(monkeypatch):
    monkeypatch.setattr(model_router, "_credential", lambda kind: ("http://local", "key"))
    result = model_router.status()
    assert result["ok"]
    assert {row["role"] for row in result["models"]} == {"daily", "fallback", "highest_urgency"}
