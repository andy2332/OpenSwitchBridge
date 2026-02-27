from __future__ import annotations

from .models import ActionActivation, ControllerState


class Arbiter:
    def __init__(self) -> None:
        self.state = ControllerState()

    def arbitrate(self, actions: list[ActionActivation]) -> ControllerState:
        self.state.clear()

        # higher priority wins for sticks
        left_best = (-1, (0.0, 0.0))
        right_best = (-1, (0.0, 0.0))

        active_actions: list[tuple[str, float]] = []

        for action in sorted(actions, key=lambda a: a.priority, reverse=True):
            if action.confidence > 0.05:
                active_actions.append((action.name, action.confidence))

            if action.left_stick is not None and action.priority > left_best[0]:
                left_best = (action.priority, action.left_stick)

            if action.right_stick is not None and action.priority > right_best[0]:
                right_best = (action.priority, action.right_stick)

            for key, pressed in action.buttons.items():
                if pressed:
                    self.state.buttons[key] = True

        self.state.left_stick = left_best[1]
        self.state.right_stick = right_best[1]
        self.state.active_actions = active_actions[:8]
        return self.state
