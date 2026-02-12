#!/usr/bin/env python3
import argparse
import math
import os
import sys
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2

try:
    import mediapipe as mp
except Exception:
    mp = None


Point = Tuple[int, int]
DEFAULT_TASK_MODEL = "pose_landmarker_full.task"
DEFAULT_TASK_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)


@dataclass
class ArmState:
    visible: bool
    shoulder: Optional[Point]
    elbow: Optional[Point]
    wrist: Optional[Point]
    angle_deg: Optional[float]
    label: str


def parse_resolution(value: str) -> Tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise ValueError("resolution format should be WIDTHxHEIGHT, e.g. 1280x720")
    width = int(parts[0])
    height = int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("resolution width/height must be > 0")
    return width, height


def calc_angle_deg(a: Point, b: Point, c: Point) -> float:
    abx = a[0] - b[0]
    aby = a[1] - b[1]
    cbx = c[0] - b[0]
    cby = c[1] - b[1]
    dot = abx * cbx + aby * cby
    norm_ab = math.hypot(abx, aby)
    norm_cb = math.hypot(cbx, cby)
    if norm_ab < 1e-6 or norm_cb < 1e-6:
        return 0.0
    cos_v = max(-1.0, min(1.0, dot / (norm_ab * norm_cb)))
    return math.degrees(math.acos(cos_v))


def classify_arm(shoulder: Point, elbow: Point, wrist: Point) -> str:
    # y smaller means higher in image coordinates.
    dy_wrist = shoulder[1] - wrist[1]
    dx_wrist = wrist[0] - shoulder[0]
    angle = calc_angle_deg(shoulder, elbow, wrist)

    if dy_wrist > 40:
        return "arm_up"
    if abs(dx_wrist) > 60 and abs(dy_wrist) < 40:
        return "arm_side"
    if angle < 90:
        return "arm_bent"
    return "arm_down"


def lm_to_point(landmark, width: int, height: int, min_visibility: float) -> Optional[Point]:
    visibility = getattr(landmark, "visibility", 1.0)
    if visibility < min_visibility:
        return None
    x = int(landmark.x * width)
    y = int(landmark.y * height)
    if x < 0 or y < 0 or x >= width or y >= height:
        return None
    return (x, y)


def detect_single_arm(landmarks, shoulder_id, elbow_id, wrist_id, width: int, height: int, min_visibility: float) -> ArmState:
    shoulder = lm_to_point(landmarks[shoulder_id], width, height, min_visibility)
    elbow = lm_to_point(landmarks[elbow_id], width, height, min_visibility)
    wrist = lm_to_point(landmarks[wrist_id], width, height, min_visibility)

    if shoulder is None or elbow is None or wrist is None:
        return ArmState(
            visible=False,
            shoulder=shoulder,
            elbow=elbow,
            wrist=wrist,
            angle_deg=None,
            label="not_visible",
        )

    angle = calc_angle_deg(shoulder, elbow, wrist)
    label = classify_arm(shoulder, elbow, wrist)
    return ArmState(
        visible=True,
        shoulder=shoulder,
        elbow=elbow,
        wrist=wrist,
        angle_deg=angle,
        label=label,
    )


def draw_arm(frame, state: ArmState, color: Tuple[int, int, int], name: str) -> None:
    if state.shoulder is not None:
        cv2.circle(frame, state.shoulder, 5, color, -1)
    if state.elbow is not None:
        cv2.circle(frame, state.elbow, 5, color, -1)
    if state.wrist is not None:
        cv2.circle(frame, state.wrist, 5, color, -1)

    if state.visible and state.shoulder and state.elbow and state.wrist:
        cv2.line(frame, state.shoulder, state.elbow, color, 3)
        cv2.line(frame, state.elbow, state.wrist, color, 3)

    if state.shoulder is not None:
        text = f"{name}:{state.label}"
        if state.angle_deg is not None:
            text += f" {state.angle_deg:.0f}deg"
        cv2.putText(
            frame,
            text,
            (state.shoulder[0] + 8, max(20, state.shoulder[1] - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )


def ensure_task_model(task_model_path: str) -> bool:
    if os.path.isfile(task_model_path):
        return True
    print(f"[INFO] task model not found, downloading: {task_model_path}")
    try:
        urllib.request.urlretrieve(DEFAULT_TASK_MODEL_URL, task_model_path)
    except Exception as exc:
        print(f"[ERROR] failed to download model: {exc}")
        print(f"[ERROR] please download manually from: {DEFAULT_TASK_MODEL_URL}")
        return False
    if not os.path.isfile(task_model_path):
        print("[ERROR] model download finished but file is missing")
        return False
    print("[INFO] model download complete")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Arm detection demo with MediaPipe Pose")
    parser.add_argument("--source", default="0", help="camera index like 0, or video file path")
    parser.add_argument("--set-res", default="", help="set camera resolution, e.g. 1280x720")
    parser.add_argument("--display-scale", type=float, default=1.0, help="display resize scale")
    parser.add_argument("--min-visibility", type=float, default=0.35, help="landmark visibility threshold")
    parser.add_argument("--model-complexity", type=int, default=1, choices=[0, 1, 2], help="mediapipe pose model complexity")
    parser.add_argument("--backend", choices=["auto", "solutions", "tasks"], default="auto",
                        help="pose backend: mediapipe solutions or tasks")
    parser.add_argument("--task-model", default=DEFAULT_TASK_MODEL,
                        help="path to pose_landmarker.task when using tasks backend")
    parser.add_argument("--no-mirror", action="store_true",
                        help="disable horizontal mirror (mirror is enabled by default)")
    args = parser.parse_args()

    if mp is None:
        print("[ERROR] mediapipe import failed. Please install with: pip install -r requirements.txt")
        return 1
    mp_version = getattr(mp, "__version__", "unknown")
    has_solutions_pose = hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")
    has_tasks_pose = False
    try:
        from mediapipe.tasks.python import BaseOptions  # type: ignore
        from mediapipe.tasks.python import vision  # type: ignore
        has_tasks_pose = hasattr(vision, "PoseLandmarker") and hasattr(vision, "PoseLandmarkerOptions")
    except Exception:
        BaseOptions = None
        vision = None

    backend = args.backend
    if backend == "auto":
        backend = "solutions" if has_solutions_pose else ("tasks" if has_tasks_pose else "none")
    if backend == "solutions" and not has_solutions_pose:
        print(f"[ERROR] requested solutions backend, but mp.solutions.pose is unavailable (mediapipe={mp_version})")
        return 1
    if backend == "tasks" and not has_tasks_pose:
        print(f"[ERROR] requested tasks backend, but mediapipe.tasks PoseLandmarker is unavailable (mediapipe={mp_version})")
        return 1
    if backend == "none":
        print(f"[ERROR] no usable pose backend found in mediapipe={mp_version}")
        return 1

    source: int | str = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERROR] failed to open source: {args.source}")
        return 1

    if args.set_res:
        try:
            req_w, req_h = parse_resolution(args.set_res)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_h)
        except ValueError as exc:
            print(f"[ERROR] invalid --set-res: {exc}")
            return 1

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[INFO] camera resolution: {actual_w}x{actual_h}")

    pose = None
    lm_enum = None
    task_landmarker = None
    task_timestamp_ms = 0
    if backend == "solutions":
        pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=args.model_complexity,
            smooth_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        lm_enum = mp.solutions.pose.PoseLandmark
        print(f"[INFO] backend=solutions mediapipe={mp_version}")
    else:
        task_model = args.task_model.strip() or DEFAULT_TASK_MODEL
        if not ensure_task_model(task_model):
            return 1
        base_options = BaseOptions(model_asset_path=task_model)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_segmentation_masks=False,
        )
        task_landmarker = vision.PoseLandmarker.create_from_options(options)
        print(f"[INFO] backend=tasks mediapipe={mp_version} model={task_model}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if not args.no_mirror:
            frame = cv2.flip(frame, 1)

        frame_h, frame_w = frame.shape[:2]
        lms = None
        left_ids = right_ids = None
        if backend == "solutions":
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = pose.process(rgb)
            if result.pose_landmarks is not None:
                lms = result.pose_landmarks.landmark
                left_ids = (int(lm_enum.LEFT_SHOULDER), int(lm_enum.LEFT_ELBOW), int(lm_enum.LEFT_WRIST))
                right_ids = (int(lm_enum.RIGHT_SHOULDER), int(lm_enum.RIGHT_ELBOW), int(lm_enum.RIGHT_WRIST))
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            task_result = task_landmarker.detect_for_video(mp_image, task_timestamp_ms)
            task_timestamp_ms += 33
            if task_result.pose_landmarks:
                lms = task_result.pose_landmarks[0]
                # PoseLandmarker landmark order follows BlazePose (33 points).
                left_ids = (11, 13, 15)
                right_ids = (12, 14, 16)

        if lms is None:
            cv2.putText(frame, "person not found", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 120, 255), 2)
        else:
            left = detect_single_arm(
                lms, left_ids[0], left_ids[1], left_ids[2], frame_w, frame_h, args.min_visibility
            )
            right = detect_single_arm(
                lms, right_ids[0], right_ids[1], right_ids[2], frame_w, frame_h, args.min_visibility
            )
            draw_arm(frame, left, (0, 220, 255), "L")
            draw_arm(frame, right, (255, 180, 0), "R")
            if left.shoulder and right.shoulder:
                cv2.line(frame, left.shoulder, right.shoulder, (0, 255, 120), 2)

        cv2.putText(
            frame,
            "q: quit",
            (20, frame_h - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
        )

        if args.display_scale != 1.0:
            view = cv2.resize(frame, None, fx=args.display_scale, fy=args.display_scale)
        else:
            view = frame
        cv2.imshow("Arm Pose Demo", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

    cap.release()
    if pose is not None:
        pose.close()
    if task_landmarker is not None:
        task_landmarker.close()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
