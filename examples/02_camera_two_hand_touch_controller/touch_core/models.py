from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


BUTTON_NAMES = [
    "A",
    "B",
    "X",
    "Y",
    "L",
    "R",
    "ZL",
    "ZR",
    "DPAD_UP",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",
]


@dataclass
class ActionActivation:
    name: str
    confidence: float
    priority: int
    buttons: Dict[str, bool] = field(default_factory=dict)
    left_stick: Tuple[float, float] | None = None
    right_stick: Tuple[float, float] | None = None


@dataclass
class ControllerState:
    buttons: Dict[str, bool] = field(default_factory=lambda: {k: False for k in BUTTON_NAMES})
    left_stick: Tuple[float, float] = (0.0, 0.0)
    right_stick: Tuple[float, float] = (0.0, 0.0)
    active_actions: List[Tuple[str, float]] = field(default_factory=list)

    def clear(self) -> None:
        for key in self.buttons:
            self.buttons[key] = False
        self.left_stick = (0.0, 0.0)
        self.right_stick = (0.0, 0.0)
        self.active_actions = []
