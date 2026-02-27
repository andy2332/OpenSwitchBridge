from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np


@dataclass
class PoseFeatures:
    torso_len: float
    shoulder_center: np.ndarray
    hip_center: np.ndarray
    head_center: np.ndarray
    left_wrist: np.ndarray
    right_wrist: np.ndarray
    left_shoulder: np.ndarray
    right_shoulder: np.ndarray
    left_hip: np.ndarray
    right_hip: np.ndarray


def _vec2(a: np.ndarray) -> np.ndarray:
    return np.array([a[0], a[1]], dtype=float)


def extract_features(landmarks: Dict[str, np.ndarray]) -> PoseFeatures | None:
    required = [
        "left_shoulder",
        "right_shoulder",
        "left_hip",
        "right_hip",
        "left_wrist",
        "right_wrist",
        "nose",
    ]
    if any(name not in landmarks for name in required):
        return None

    ls = _vec2(landmarks["left_shoulder"])
    rs = _vec2(landmarks["right_shoulder"])
    lh = _vec2(landmarks["left_hip"])
    rh = _vec2(landmarks["right_hip"])
    lw = _vec2(landmarks["left_wrist"])
    rw = _vec2(landmarks["right_wrist"])
    nose = _vec2(landmarks["nose"])

    shoulder_center = (ls + rs) * 0.5
    hip_center = (lh + rh) * 0.5
    torso_len = float(np.linalg.norm(shoulder_center - hip_center))

    return PoseFeatures(
        torso_len=torso_len,
        shoulder_center=shoulder_center,
        hip_center=hip_center,
        head_center=nose,
        left_wrist=lw,
        right_wrist=rw,
        left_shoulder=ls,
        right_shoulder=rs,
        left_hip=lh,
        right_hip=rh,
    )
