from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np


@dataclass
class EMA:
    alpha: float
    value: np.ndarray | None = None

    def update(self, x: np.ndarray) -> np.ndarray:
        if self.value is None:
            self.value = x.astype(float)
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class LandmarkEMAFilter:
    def __init__(self, alpha_xy: float) -> None:
        self.alpha_xy = alpha_xy
        self._filters: Dict[str, EMA] = {}

    def update(self, landmarks: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        out: Dict[str, np.ndarray] = {}
        for name, p in landmarks.items():
            if name not in self._filters:
                self._filters[name] = EMA(alpha=self.alpha_xy)
            smoothed_xy = self._filters[name].update(p[:2])
            out[name] = np.array([smoothed_xy[0], smoothed_xy[1], p[2]], dtype=float)
        return out
