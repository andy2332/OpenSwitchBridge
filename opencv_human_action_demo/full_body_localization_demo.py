#!/usr/bin/env python3
import argparse
import os
import urllib.request
from typing import List, Optional, Tuple

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

# BlazePose 33-keypoint skeleton edges.
SKELETON_PAIRS = [
    (11, 12),
    (11, 13), (13, 15),
    (12, 14), (14, 16),
    (15, 17), (15, 19), (15, 21),
    (16, 18), (16, 20), (16, 22),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31),
    (24, 26), (26, 28), (28, 30), (30, 32),
]


def parse_resolution(value: str) -> Tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise ValueError("resolution format should be WIDTHxHEIGHT, e.g. 1280x720")
    width = int(parts[0])
    height = int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("resolution width/height must be > 0")
    return width, height


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


def lm_to_point(landmark, width: int, height: int, min_visibility: float) -> Optional[Point]:
    visibility = getattr(landmark, "visibility", 1.0)
    if visibility < min_visibility:
        return None
    x = int(landmark.x * width)
    y = int(landmark.y * height)
    if x < 0 or y < 0 or x >= width or y >= height:
        return None
    return (x, y)


def draw_full_body(frame, landmarks, min_visibility: float) -> Tuple[bool, int]:
    h, w = frame.shape[:2]
    points: List[Optional[Point]] = [lm_to_point(lm, w, h, min_visibility) for lm in landmarks]

    visible_points = [p for p in points if p is not None]
    if not visible_points:
        return False, 0

    for a, b in SKELETON_PAIRS:
        pa = points[a] if a < len(points) else None
        pb = points[b] if b < len(points) else None
        if pa is not None and pb is not None:
            cv2.line(frame, pa, pb, (0, 220, 255), 2)

    for p in visible_points:
        cv2.circle(frame, p, 3, (255, 255, 255), -1)

    xs = [p[0] for p in visible_points]
    ys = [p[1] for p in visible_points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (32, 220, 32), 2)

    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    cv2.circle(frame, (cx, cy), 4, (0, 255, 120), -1)
    cv2.putText(
        frame,
        f"full_body points={len(visible_points)}",
        (x0, max(20, y0 - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (20, 250, 20),
        2,
    )
    return True, len(visible_points)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCV full-body localization demo")
    parser.add_argument("--source", default="0", help="camera index like 0, or video file path")
    parser.add_argument("--set-res", default="", help="set camera resolution, e.g. 1280x720")
    parser.add_argument("--display-scale", type=float, default=1.0, help="display resize scale")
    parser.add_argument("--min-visibility", type=float, default=0.35, help="landmark visibility threshold")
    parser.add_argument("--model-complexity", type=int, default=1, choices=[0, 1, 2],
                        help="mediapipe pose model complexity (solutions backend)")
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

        landmarks = None
        if backend == "solutions":
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = pose.process(rgb)
            if result.pose_landmarks is not None:
                landmarks = result.pose_landmarks.landmark
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            task_result = task_landmarker.detect_for_video(mp_image, task_timestamp_ms)
            task_timestamp_ms += 33
            if task_result.pose_landmarks:
                landmarks = task_result.pose_landmarks[0]

        if landmarks is None:
            cv2.putText(frame, "person not found", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 120, 255), 2)
        else:
            draw_full_body(frame, landmarks, args.min_visibility)

        cv2.putText(
            frame,
            "q: quit",
            (20, frame.shape[0] - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
        )

        if args.display_scale != 1.0:
            view = cv2.resize(frame, None, fx=args.display_scale, fy=args.display_scale)
        else:
            view = frame
        cv2.imshow("OpenCV Full-Body Localization Demo", view)

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
