from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2


TIMECODE_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


@dataclass
class Segment:
    index: int
    start: float
    end: float


def _time_to_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _read_srt(path: Path) -> list[Segment]:
    raw = path.read_text(encoding="utf-8-sig")
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", raw.strip(), flags=re.MULTILINE):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        match = next((TIMECODE_RE.search(line) for line in lines[:2] if TIMECODE_RE.search(line)), None)
        if not match:
            continue
        try:
            index = int(lines[0])
        except ValueError:
            index = len(segments) + 1
        segments.append(
            Segment(
                index=index,
                start=_time_to_seconds(match.group("start")),
                end=_time_to_seconds(match.group("end")),
            )
        )
    return segments


def _coordinates(polygons) -> list[tuple[int, int, int, int]]:
    boxes = []
    if polygons is None:
        return boxes
    for polygon in polygons:
        points = polygon.tolist() if hasattr(polygon, "tolist") else polygon
        if not points:
            continue
        xs = [int(round(point[0])) for point in points]
        ys = [int(round(point[1])) for point in points]
        boxes.append((min(xs), max(xs), min(ys), max(ys)))
    return boxes


def _detect_boxes(detector, frame) -> list[tuple[int, int, int, int]]:
    boxes: list[tuple[int, int, int, int]] = []
    for result in detector.predict(frame):
        try:
            polygons = result["dt_polys"]
        except (KeyError, TypeError):
            polygons = getattr(result, "dt_polys", None)
        if polygons is not None:
            boxes.extend(_coordinates(polygons))
    return boxes


def _select_subtitle_band(
    boxes: list[tuple[int, int, int, int]],
    *,
    width: int,
    height: int,
    crop_x: int,
    crop_y: int,
) -> tuple[int, int, int, int] | None:
    candidates: list[tuple[int, int, int, int]] = []
    min_height = max(5, int(height * 0.008))
    max_height = max(min_height + 1, int(height * 0.18))
    for xmin, xmax, ymin, ymax in boxes:
        xmin += crop_x
        xmax += crop_x
        ymin += crop_y
        ymax += crop_y
        box_width = xmax - xmin
        box_height = ymax - ymin
        if box_width < max(8, int(width * 0.012)):
            continue
        if box_height < min_height or box_height > max_height:
            continue
        candidates.append((xmin, xmax, ymin, ymax))
    if not candidates:
        return None

    def score(box: tuple[int, int, int, int]) -> float:
        xmin, xmax, ymin, ymax = box
        center_x = (xmin + xmax) / (2 * width)
        width_ratio = (xmax - xmin) / width
        center_score = max(0.0, 1.0 - abs(center_x - 0.5) / 0.45)
        lower_score = (ymin + ymax) / (2 * height)
        return min(width_ratio, 0.8) * 4.0 + center_score * 1.4 + lower_score * 0.35

    primary = max(candidates, key=score)
    selected = [primary]
    pxmin, pxmax, pymin, pymax = primary
    vertical_gap = max(10, int(height * 0.055))
    for box in candidates:
        if box == primary:
            continue
        xmin, xmax, ymin, ymax = box
        gap = max(0, max(ymin, pymin) - min(ymax, pymax))
        horizontal_overlap = max(0, min(xmax, pxmax) - max(xmin, pxmin))
        centered = abs((xmin + xmax) / 2 - width / 2) <= width * 0.34
        if gap <= vertical_gap and (horizontal_overlap > 0 or centered):
            selected.append(box)

    return (
        min(box[0] for box in selected),
        max(box[1] for box in selected),
        min(box[2] for box in selected),
        max(box[3] for box in selected),
    )


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return int(round((ordered[midpoint - 1] + ordered[midpoint]) / 2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect hard-subtitle vertical masks at SRT timestamps.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--xmin", type=float, default=0.04)
    parser.add_argument("--xmax", type=float, default=0.96)
    parser.add_argument("--ymin", type=float, default=0.30)
    parser.add_argument("--ymax", type=float, default=0.99)
    parser.add_argument("--exact-box", action="store_true")
    parser.add_argument("--single-sample", action="store_true")
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    srt_path = Path(args.srt).resolve()
    output_path = Path(args.output).resolve()
    segments = _read_srt(srt_path)
    if not segments:
        raise RuntimeError("The selected SRT does not contain any timed subtitle segments.")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    if width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("Could not read video dimensions.")

    search_xmin = max(0, min(width - 2, int(round(width * args.xmin))))
    search_xmax = max(search_xmin + 2, min(width, int(round(width * args.xmax))))
    search_ymin = max(0, min(height - 2, int(round(height * args.ymin))))
    search_ymax = max(search_ymin + 2, min(height, int(round(height * args.ymax))))

    # PaddleX imports ModelScope, which imports Torch. On Windows, loading Paddle
    # first can leave Torch's shm.dll with unresolved symbols, so establish the
    # Torch DLL set before initializing PaddleOCR.
    import torch  # noqa: F401
    import paddle

    paddle.disable_signal_handler()
    from paddleocr import TextDetection

    detector = TextDetection(
        model_name="PP-OCRv5_mobile_det",
        model_dir=str(Path(args.model_dir).resolve()),
        device="cpu",
        enable_hpi=False,
    )

    detections: list[dict] = []
    total = len(segments)
    for position, segment in enumerate(segments, start=1):
        sample_times = [(segment.start + segment.end) / 2]
        duration = max(0.0, segment.end - segment.start)
        if duration >= 1.0 and not args.single_sample:
            sample_times.extend([segment.start + duration * 0.35, segment.start + duration * 0.65])

        selected = None
        raw_count = 0
        for sample_time in sample_times:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, sample_time * 1000))
            ok, frame = capture.read()
            if not ok:
                continue
            crop = frame[search_ymin:search_ymax, search_xmin:search_xmax]
            boxes = _detect_boxes(detector, crop)
            raw_count = max(raw_count, len(boxes))
            selected = _select_subtitle_band(
                boxes,
                width=width,
                height=height,
                crop_x=search_xmin,
                crop_y=search_ymin,
            )
            if selected:
                break
        detections.append(
            {
                "index": segment.index,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "detected_bbox": list(selected) if selected else None,
                "raw_box_count": raw_count,
            }
        )
        print(f"MASK_PROGRESS {position}/{total}", flush=True)

    capture.release()
    successful = [item["detected_bbox"] for item in detections if item["detected_bbox"]]
    if not successful:
        raise RuntimeError(
            "No subtitle text was detected at the SRT timestamps. Check that this is the original SRT and video."
        )

    median_ymin = _median([box[2] for box in successful])
    median_ymax = _median([box[3] for box in successful])
    median_height = max(6, _median([box[3] - box[2] for box in successful]))
    padding_y = max(4, int(round(height * 0.009)))
    padding_x = max(6, int(round(width * 0.012)))
    max_center_deviation = max(int(height * 0.14), median_height * 2)
    fallback_count = 0
    plan_segments = []
    for item in detections:
        box = item.pop("detected_bbox")
        source = "detected"
        if box:
            center = (box[2] + box[3]) // 2
            median_center = (median_ymin + median_ymax) // 2
            if abs(center - median_center) > max_center_deviation:
                box = None
        if not box:
            box = [search_xmin, search_xmax, median_ymin, median_ymax]
            source = "fallback"
            fallback_count += 1
        ymin = max(search_ymin, int(box[2]) - padding_y)
        ymax = min(search_ymax, int(box[3]) + padding_y)
        xmin = max(search_xmin, int(box[0]) - padding_x) if args.exact_box and source == "detected" else search_xmin
        xmax = min(search_xmax, int(box[1]) + padding_x) if args.exact_box and source == "detected" else search_xmax
        plan_segments.append(
            {
                **item,
                "bbox": {
                    "xmin": xmin,
                    "xmax": max(xmin + 2, xmax),
                    "ymin": ymin,
                    "ymax": max(ymin + 2, ymax),
                },
                "source": source,
            }
        )

    payload = {
        "version": 1,
        "detector": "PP-OCRv5_mobile_det",
        "video": str(video_path),
        "srt": str(srt_path),
        "source_mtime_ns": {
            "video": video_path.stat().st_mtime_ns,
            "srt": srt_path.stat().st_mtime_ns,
        },
        "width": width,
        "height": height,
        "search_area": {
            "xmin": search_xmin,
            "xmax": search_xmax,
            "ymin": search_ymin,
            "ymax": search_ymax,
        },
        "segments": plan_segments,
        "stats": {
            "segments": total,
            "detected": total - fallback_count,
            "fallback": fallback_count,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"MASK_RESULT {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"MASK_ERROR {exc}", file=sys.stderr, flush=True)
        raise
