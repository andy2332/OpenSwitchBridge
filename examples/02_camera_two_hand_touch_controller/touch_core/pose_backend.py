from __future__ import annotations

from typing import Dict

import cv2
import mediapipe as mp
import numpy as np

LANDMARK_NAME = {
    0: "nose",
    11: "left_shoulder",
    12: "right_shoulder",
    23: "left_hip",
    24: "right_hip",
    15: "left_wrist",
    16: "right_wrist",
    13: "left_elbow",
    14: "right_elbow",
}


class PoseBackend:
    def __init__(self, pose_cfg: dict):
        if not hasattr(mp, "solutions"):
            raise RuntimeError(
                "Current mediapipe package does not expose mp.solutions Pose API. "
                "Please use Python 3.11/3.12 and install: mediapipe==0.10.14"
            )

        self.mp_pose = mp.solutions.pose
        self.mp_draw = mp.solutions.drawing_utils
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=int(pose_cfg.get("model_complexity", 1)),
            smooth_landmarks=True,
            min_detection_confidence=float(pose_cfg.get("min_detection_confidence", 0.5)),
            min_tracking_confidence=float(pose_cfg.get("min_tracking_confidence", 0.5)),
        )

    def infer(self, frame_bgr: np.ndarray):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return self.pose.process(rgb)

    def to_landmark_dict(self, result) -> Dict[str, np.ndarray]:
        out: Dict[str, np.ndarray] = {}
        if not result.pose_landmarks:
            return out

        for idx, lm in enumerate(result.pose_landmarks.landmark):
            name = LANDMARK_NAME.get(idx)
            if name is None:
                continue
            out[name] = np.array([lm.x, lm.y, lm.visibility], dtype=float)
        return out

    def draw_skeleton(self, frame_bgr: np.ndarray, result) -> None:
        if not result.pose_landmarks:
            return
        self.mp_draw.draw_landmarks(
            frame_bgr,
            result.pose_landmarks,
            self.mp_pose.POSE_CONNECTIONS,
        )
