"""The rework path must retain timed scenes instead of collapsing them."""
from src import orchestrator


def test_rework_keeps_timed_scenes(monkeypatch):
    original = "(0-3s) Garage: he turns. (3-7s) Cut to street: he runs."
    captured = []

    def generate(client, model, instruction, **kwargs):
        captured.append(instruction)
        return original

    monkeypatch.setattr(orchestrator, "_client", lambda: None)
    monkeypatch.setattr(orchestrator, "generate_with_retry", generate)
    result = orchestrator._rework_shot_prompt(
        original, {"dims": {"motion": 0}, "reason": "too many sequential actions"})
    assert result == original
    assert original in captured[0]
    assert "Multiple scenes, cuts and sequential actions are allowed" in captured[0]
    assert "Keep explicit time duration markers" in captured[0]
    assert "Delete every numbered stage" not in captured[0]
    assert "COLLAPSING to a single beat" not in captured[0]
