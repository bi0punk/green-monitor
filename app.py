#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DEFAULT_SAMPLE_IMAGE = DATA_DIR / "sample_baseline.png"
DEFAULT_ROI_FILE = DATA_DIR / "roi_polygon.json"
DEFAULT_STATE_FILE = DATA_DIR / "app_state.json"
DEFAULT_HISTORY_CSV_FILE = DATA_DIR / "growth_history.csv"
DEFAULT_HISTORY_LATEST_FILE = DATA_DIR / "history_latest.json"
DEFAULT_HISTORY_WINDOW_FILE = DATA_DIR / "history_window.json"

STREAM_SOURCE = os.getenv("STREAM_SOURCE", str(DEFAULT_SAMPLE_IMAGE))
ROI_JSON_PATH = Path(os.getenv("ROI_JSON_PATH", str(DEFAULT_ROI_FILE)))
STATE_JSON_PATH = Path(os.getenv("STATE_JSON_PATH", str(DEFAULT_STATE_FILE)))
HISTORY_CSV_PATH = Path(os.getenv("HISTORY_CSV_PATH", str(DEFAULT_HISTORY_CSV_FILE)))
HISTORY_LATEST_PATH = Path(os.getenv("HISTORY_LATEST_PATH", str(DEFAULT_HISTORY_LATEST_FILE)))
HISTORY_WINDOW_PATH = Path(os.getenv("HISTORY_WINDOW_PATH", str(DEFAULT_HISTORY_WINDOW_FILE)))

FRAME_WAIT = float(os.getenv("FRAME_WAIT", "0.2"))
AUTO_BASELINE_ON_START = os.getenv("AUTO_BASELINE_ON_START", "1") == "1"
MIN_CONTOUR_AREA = float(os.getenv("MIN_CONTOUR_AREA", "10"))
CONTOUR_FILL_ALPHA = float(os.getenv("CONTOUR_FILL_ALPHA", "0.35"))
HISTORY_SAVE_MINUTES = max(1, int(os.getenv("HISTORY_SAVE_MINUTES", "5")))
HISTORY_SAVE_SECONDS = HISTORY_SAVE_MINUTES * 60

app = Flask(__name__, template_folder="templates", static_folder="static")


def clamp_point(x: int, y: int, w: int, h: int) -> Tuple[int, int]:
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    return x, y


def format_ts(epoch_seconds: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch_seconds))


def read_history_rows(csv_path: Path, limit: int = 240) -> List[dict]:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    rows: List[dict] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "bucket_start_epoch": int(float(row.get("bucket_start_epoch") or 0)),
                    "bucket_end_epoch": int(float(row.get("bucket_end_epoch") or 0)),
                    "bucket_start": row.get("bucket_start") or "",
                    "bucket_end": row.get("bucket_end") or "",
                    "peak_timestamp": row.get("peak_timestamp") or "",
                    "peak_growth_pct": float(row.get("peak_growth_pct") or 0.0),
                    "peak_green_coverage_pct": float(row.get("peak_green_coverage_pct") or 0.0),
                    "baseline_green_pct": float(row.get("baseline_green_pct") or 0.0),
                    "green_pixels": int(float(row.get("green_pixels") or 0)),
                    "roi_area_px": int(float(row.get("roi_area_px") or 0)),
                    "green_blobs": int(float(row.get("green_blobs") or 0)),
                    "largest_blob_area": float(row.get("largest_blob_area") or 0.0),
                    "source_mode": row.get("source_mode") or "",
                    "roi_ready": str(row.get("roi_ready") or "").lower() in {"1", "true", "yes", "si"},
                    "baseline_ready": str(row.get("baseline_ready") or "").lower() in {"1", "true", "yes", "si"},
                    "saved_at": row.get("saved_at") or "",
                })
    except Exception:
        return []

    rows.sort(key=lambda r: r.get("bucket_start_epoch", 0))
    if limit > 0:
        rows = rows[-limit:]
    return rows


class StreamAnalyzer:
    def __init__(
        self,
        source: str,
        roi_json_path: Path,
        state_json_path: Path,
        history_csv_path: Path,
        history_latest_path: Path,
        history_window_path: Path,
        history_save_seconds: int,
    ):
        self.source = source
        self.roi_json_path = roi_json_path
        self.state_json_path = state_json_path
        self.history_csv_path = history_csv_path
        self.history_latest_path = history_latest_path
        self.history_window_path = history_window_path
        self.history_save_seconds = max(60, int(history_save_seconds))

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.capture: Optional[cv2.VideoCapture] = None
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_overlay: Optional[np.ndarray] = None
        self.latest_green_mask: Optional[np.ndarray] = None
        self.roi_points: List[Tuple[int, int]] = []
        self.baseline_green_pct: Optional[float] = None
        self.baseline_ready = False
        self.last_error: Optional[str] = None
        self.source_mode = "unknown"

        self.current_history_bucket_start: Optional[int] = None
        self.current_history_bucket_end: Optional[int] = None
        self.current_history_peak: Optional[Dict] = None
        self.latest_history_saved: Optional[Dict] = None

        self.latest_metrics = {
            "timestamp": None,
            "roi_area_px": 0,
            "green_pixels": 0,
            "green_coverage_pct": 0.0,
            "growth_pct": 0.0,
            "baseline_green_pct": None,
            "roi_ready": False,
            "baseline_ready": False,
            "source_mode": self.source_mode,
            "history_save_minutes": HISTORY_SAVE_MINUTES,
            "history_last_saved_at": None,
            "history_last_peak_growth_pct": 0.0,
            "history_current_window_peak_growth_pct": 0.0,
        }

        self._load_roi()
        self._load_state()
        self._load_history_runtime_state()

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _safe_read_json(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.last_error = f"No se pudo leer {path.name}: {exc}"
            return None

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_roi(self) -> None:
        data = self._safe_read_json(self.roi_json_path)
        if not data:
            return
        points = data.get("points", [])
        parsed: List[Tuple[int, int]] = []
        for p in points:
            if isinstance(p, dict):
                parsed.append((int(p["x"]), int(p["y"])))
            elif isinstance(p, (list, tuple)) and len(p) == 2:
                parsed.append((int(p[0]), int(p[1])))
        if len(parsed) >= 3:
            self.roi_points = parsed

    def _save_roi(self) -> None:
        data = {
            "version": 1,
            "roi_type": "polygon",
            "points": [{"x": int(x), "y": int(y)} for x, y in self.roi_points],
        }
        self._write_json(self.roi_json_path, data)

    def _load_state(self) -> None:
        data = self._safe_read_json(self.state_json_path)
        if not data:
            return
        baseline = data.get("baseline_green_pct")
        if baseline is not None:
            self.baseline_green_pct = float(baseline)
            self.baseline_ready = True

    def _save_state(self) -> None:
        data = {
            "baseline_green_pct": self.baseline_green_pct,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._write_json(self.state_json_path, data)

    def _load_history_runtime_state(self) -> None:
        latest = self._safe_read_json(self.history_latest_path)
        if isinstance(latest, dict):
            self.latest_history_saved = latest

        window = self._safe_read_json(self.history_window_path)
        if not isinstance(window, dict):
            return

        now_bucket_start = self._bucket_start_epoch(int(time.time()))
        if int(window.get("bucket_start_epoch", -1)) == now_bucket_start:
            self.current_history_bucket_start = now_bucket_start
            self.current_history_bucket_end = now_bucket_start + self.history_save_seconds
            self.current_history_peak = window
        else:
            try:
                self.history_window_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        if Path(self.source).exists() and Path(self.source).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            self.source_mode = "image"
            return None

        if str(self.source).isdigit():
            cap = cv2.VideoCapture(int(self.source))
            self.source_mode = "camera"
        else:
            cap = cv2.VideoCapture(self.source)
            self.source_mode = "stream"

        if not cap.isOpened():
            self.last_error = f"No se pudo abrir fuente: {self.source}. Usando imagen fallback."
            self.source_mode = "image"
            self.source = str(DEFAULT_SAMPLE_IMAGE)
            return None
        return cap

    def _get_source_frame(self) -> Optional[np.ndarray]:
        if self.source_mode == "image":
            img = cv2.imread(str(self.source))
            if img is None:
                self.last_error = f"No se pudo leer imagen fallback: {self.source}"
            return img

        if self.capture is None:
            return None

        ok, frame = self.capture.read()
        if not ok or frame is None:
            self.last_error = "Fallo de lectura del stream, reintentando..."
            with self.lock:
                try:
                    self.capture.release()
                except Exception:
                    pass
                self.capture = self._open_capture()
            return None
        return frame

    def _create_roi_mask(self, shape: Tuple[int, int, int], points: List[Tuple[int, int]]) -> np.ndarray:
        h, w = shape[:2]
        if len(points) < 3:
            return np.ones((h, w), dtype=np.uint8) * 255
        polygon = np.array([clamp_point(x, y, w, h) for x, y in points], dtype=np.int32)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [polygon], 255)
        return mask

    def _green_mask(self, frame: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        b, g, r = cv2.split(frame.astype(np.int16))
        exg = 2 * g - r - b
        h = hsv[:, :, 0]
        s = hsv[:, :, 1]
        v = hsv[:, :, 2]

        mask_hsv = ((h >= 28) & (h <= 95) & (s >= 25) & (v >= 20))
        mask_exg = exg >= 18
        mask = np.where(mask_hsv & mask_exg, 255, 0).astype(np.uint8)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        highlight_mask = np.where((gray >= 245) & (s <= 25), 255, 0).astype(np.uint8)
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(highlight_mask))

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        return mask

    def _analyze(self, frame: np.ndarray) -> Tuple[np.ndarray, dict, np.ndarray]:
        roi_mask = self._create_roi_mask(frame.shape, self.roi_points)
        green_mask = self._green_mask(frame)
        green_mask_roi = cv2.bitwise_and(green_mask, roi_mask)

        roi_area = int(np.count_nonzero(roi_mask))
        green_pixels = int(np.count_nonzero(green_mask_roi))
        green_coverage_pct = (green_pixels / roi_area * 100.0) if roi_area > 0 else 0.0

        if AUTO_BASELINE_ON_START and not self.baseline_ready and roi_area > 0:
            self.baseline_green_pct = green_coverage_pct
            self.baseline_ready = True
            self._save_state()

        baseline_green_pct = self.baseline_green_pct if self.baseline_green_pct is not None else 0.0
        growth_pct = max(0.0, green_coverage_pct - baseline_green_pct)

        overlay = frame.copy()
        outside_mask = cv2.bitwise_not(roi_mask)
        overlay[outside_mask > 0] = (overlay[outside_mask > 0] * 0.25).astype(np.uint8)

        if len(self.roi_points) >= 3:
            pts = np.array(self.roi_points, dtype=np.int32)
            cv2.polylines(overlay, [pts], True, (255, 200, 0), 2)

        contours, _ = cv2.findContours(green_mask_roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        kept = 0
        contour_fill = np.zeros_like(frame)
        contour_areas = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < MIN_CONTOUR_AREA:
                continue
            kept += 1
            contour_areas.append(float(area))
            cv2.drawContours(contour_fill, [cnt], -1, (0, 180, 0), thickness=cv2.FILLED)
            cv2.drawContours(overlay, [cnt], -1, (0, 255, 0), thickness=2)

            x, y, bw, bh = cv2.boundingRect(cnt)
            cv2.rectangle(overlay, (x, y), (x + bw, y + bh), (90, 255, 90), 1)

            moments = cv2.moments(cnt)
            if moments["m00"] != 0:
                cx = int(moments["m10"] / moments["m00"])
                cy = int(moments["m01"] / moments["m00"])
                cv2.circle(overlay, (cx, cy), 3, (0, 255, 255), -1)

        overlay = cv2.addWeighted(overlay, 1.0, contour_fill, CONTOUR_FILL_ALPHA, 0)
        largest_blob_area = max(contour_areas) if contour_areas else 0.0

        cv2.putText(overlay, f"Cobertura verde ROI: {green_coverage_pct:.2f}%", (18, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.putText(overlay, f"Crecimiento vs baseline: {growth_pct:.2f}%", (18, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2, cv2.LINE_AA)
        cv2.putText(overlay, f"Baseline verde: {baseline_green_pct:.2f}%", (18, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(overlay, f"Blobs verdes: {kept}", (18, 118),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

        metrics = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "roi_area_px": roi_area,
            "green_pixels": green_pixels,
            "green_coverage_pct": round(float(green_coverage_pct), 4),
            "growth_pct": round(float(growth_pct), 4),
            "baseline_green_pct": round(float(baseline_green_pct), 4),
            "roi_ready": len(self.roi_points) >= 3,
            "baseline_ready": bool(self.baseline_ready),
            "source_mode": self.source_mode,
            "green_blobs": kept,
            "largest_blob_area": round(float(largest_blob_area), 2),
            "frame_width": frame.shape[1],
            "frame_height": frame.shape[0],
            "error": self.last_error,
        }
        return overlay, metrics, green_mask_roi

    def _bucket_start_epoch(self, epoch_seconds: int) -> int:
        return int(epoch_seconds // self.history_save_seconds) * self.history_save_seconds

    def _build_history_entry(self, metrics: dict, bucket_start: int) -> dict:
        bucket_end = bucket_start + self.history_save_seconds
        return {
            "bucket_start_epoch": int(bucket_start),
            "bucket_end_epoch": int(bucket_end),
            "bucket_start": format_ts(bucket_start),
            "bucket_end": format_ts(bucket_end),
            "peak_timestamp": metrics.get("timestamp"),
            "peak_growth_pct": round(float(metrics.get("growth_pct") or 0.0), 4),
            "peak_green_coverage_pct": round(float(metrics.get("green_coverage_pct") or 0.0), 4),
            "baseline_green_pct": round(float(metrics.get("baseline_green_pct") or 0.0), 4),
            "green_pixels": int(metrics.get("green_pixels") or 0),
            "roi_area_px": int(metrics.get("roi_area_px") or 0),
            "green_blobs": int(metrics.get("green_blobs") or 0),
            "largest_blob_area": round(float(metrics.get("largest_blob_area") or 0.0), 2),
            "source_mode": metrics.get("source_mode") or self.source_mode,
            "roi_ready": bool(metrics.get("roi_ready")),
            "baseline_ready": bool(metrics.get("baseline_ready")),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _is_better_history_entry(self, candidate: dict, current: Optional[dict]) -> bool:
        if current is None:
            return True

        candidate_growth = float(candidate.get("peak_growth_pct") or 0.0)
        current_growth = float(current.get("peak_growth_pct") or 0.0)
        if candidate_growth > current_growth:
            return True
        if candidate_growth < current_growth:
            return False

        candidate_cov = float(candidate.get("peak_green_coverage_pct") or 0.0)
        current_cov = float(current.get("peak_green_coverage_pct") or 0.0)
        if candidate_cov > current_cov:
            return True
        if candidate_cov < current_cov:
            return False

        candidate_pixels = int(candidate.get("green_pixels") or 0)
        current_pixels = int(current.get("green_pixels") or 0)
        return candidate_pixels > current_pixels

    def _append_history_csv(self, row: dict) -> None:
        self.history_csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "bucket_start_epoch",
            "bucket_end_epoch",
            "bucket_start",
            "bucket_end",
            "peak_timestamp",
            "peak_growth_pct",
            "peak_green_coverage_pct",
            "baseline_green_pct",
            "green_pixels",
            "roi_area_px",
            "green_blobs",
            "largest_blob_area",
            "source_mode",
            "roi_ready",
            "baseline_ready",
            "saved_at",
        ]
        write_header = not self.history_csv_path.exists() or self.history_csv_path.stat().st_size == 0
        with self.history_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerow({k: row.get(k) for k in fieldnames})

    def _persist_current_history_window(self) -> None:
        if self.current_history_peak is None:
            return
        self._write_json(self.history_window_path, self.current_history_peak)

    def _finalize_current_history_bucket(self) -> None:
        if self.current_history_peak is None:
            return
        row = dict(self.current_history_peak)
        row["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._append_history_csv(row)
        self.latest_history_saved = row
        self._write_json(self.history_latest_path, row)
        self.current_history_peak = None
        try:
            self.history_window_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _reset_current_history_window(self) -> None:
        self.current_history_bucket_start = None
        self.current_history_bucket_end = None
        self.current_history_peak = None
        try:
            self.history_window_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _update_history(self, metrics: dict) -> None:
        epoch_now = int(time.time())
        bucket_start = self._bucket_start_epoch(epoch_now)
        bucket_end = bucket_start + self.history_save_seconds

        if self.current_history_bucket_start is None:
            self.current_history_bucket_start = bucket_start
            self.current_history_bucket_end = bucket_end
        elif bucket_start != self.current_history_bucket_start:
            self._finalize_current_history_bucket()
            self.current_history_bucket_start = bucket_start
            self.current_history_bucket_end = bucket_end
            self.current_history_peak = None

        candidate = self._build_history_entry(metrics, bucket_start)
        if self._is_better_history_entry(candidate, self.current_history_peak):
            self.current_history_peak = candidate
            self._persist_current_history_window()

    def _history_status_fields(self) -> dict:
        latest_saved = self.latest_history_saved or {}
        current_peak = self.current_history_peak or {}
        return {
            "history_save_minutes": int(self.history_save_seconds // 60),
            "history_csv_path": str(self.history_csv_path),
            "history_latest_path": str(self.history_latest_path),
            "history_last_saved_at": latest_saved.get("saved_at"),
            "history_last_peak_growth_pct": round(float(latest_saved.get("peak_growth_pct") or 0.0), 4),
            "history_last_peak_green_coverage_pct": round(float(latest_saved.get("peak_green_coverage_pct") or 0.0), 4),
            "history_last_bucket_start": latest_saved.get("bucket_start"),
            "history_current_window_peak_growth_pct": round(float(current_peak.get("peak_growth_pct") or 0.0), 4),
            "history_current_window_peak_green_coverage_pct": round(float(current_peak.get("peak_green_coverage_pct") or 0.0), 4),
            "history_current_window_start": current_peak.get("bucket_start") or (format_ts(self.current_history_bucket_start) if self.current_history_bucket_start else None),
            "history_current_window_end": current_peak.get("bucket_end") or (format_ts(self.current_history_bucket_end) if self.current_history_bucket_end else None),
        }

    def _decorate_metrics_with_history(self, metrics: dict) -> dict:
        combined = dict(metrics)
        combined.update(self._history_status_fields())
        return combined

    def _run(self) -> None:
        self.capture = self._open_capture()
        while not self.stop_event.is_set():
            frame = self._get_source_frame()
            if frame is None:
                time.sleep(max(FRAME_WAIT, 0.2))
                continue

            overlay, metrics, green_mask = self._analyze(frame)
            with self.lock:
                self._update_history(metrics)
                metrics = self._decorate_metrics_with_history(metrics)
                self.latest_frame = frame
                self.latest_overlay = overlay
                self.latest_green_mask = green_mask
                self.latest_metrics = metrics
            time.sleep(FRAME_WAIT)

    def get_overlay_jpeg(self) -> bytes:
        with self.lock:
            frame = self.latest_overlay.copy() if self.latest_overlay is not None else None
        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "Esperando fuente de video...", (40, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if ok else b""

    def get_raw_frame_jpeg(self) -> bytes:
        with self.lock:
            frame = self.latest_frame.copy() if self.latest_frame is not None else None
        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        return buf.tobytes() if ok else b""

    def get_metrics(self) -> dict:
        with self.lock:
            return dict(self.latest_metrics)

    def set_roi(self, points: List[Tuple[int, int]]) -> dict:
        with self.lock:
            if self.latest_frame is None:
                raise RuntimeError("Aún no hay frame disponible")
            h, w = self.latest_frame.shape[:2]
            clean_points = [clamp_point(x, y, w, h) for x, y in points]
            if len(clean_points) < 3:
                raise ValueError("El ROI requiere al menos 3 puntos")
            self.roi_points = clean_points
            self._save_roi()
            _, metrics, _ = self._analyze(self.latest_frame)
            self.baseline_green_pct = float(metrics["green_coverage_pct"])
            self.baseline_ready = True
            self._save_state()
            self._reset_current_history_window()
            _, metrics, _ = self._analyze(self.latest_frame)
            self.latest_metrics = self._decorate_metrics_with_history(metrics)
            return {"ok": True, "roi_points": self.roi_points, "baseline_green_pct": self.baseline_green_pct}

    def reset_baseline_from_current(self) -> dict:
        with self.lock:
            if self.latest_frame is None:
                raise RuntimeError("Aún no hay frame disponible")
            _, metrics, _ = self._analyze(self.latest_frame)
            self.baseline_green_pct = float(metrics["green_coverage_pct"])
            self.baseline_ready = True
            self._save_state()
            self._reset_current_history_window()
            _, metrics, _ = self._analyze(self.latest_frame)
            self.latest_metrics = self._decorate_metrics_with_history(metrics)
            return {"ok": True, "baseline_green_pct": self.baseline_green_pct, "metrics": self.latest_metrics}

    def get_roi_points(self) -> List[Tuple[int, int]]:
        with self.lock:
            return list(self.roi_points)

    def get_latest_history(self) -> dict:
        with self.lock:
            return {
                "latest_saved": dict(self.latest_history_saved) if self.latest_history_saved else None,
                "current_window": dict(self.current_history_peak) if self.current_history_peak else None,
                "history_save_minutes": int(self.history_save_seconds // 60),
                "history_csv_path": str(self.history_csv_path),
            }


analyzer = StreamAnalyzer(
    STREAM_SOURCE,
    ROI_JSON_PATH,
    STATE_JSON_PATH,
    HISTORY_CSV_PATH,
    HISTORY_LATEST_PATH,
    HISTORY_WINDOW_PATH,
    HISTORY_SAVE_SECONDS,
)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            frame = analyzer.get_overlay_jpeg()
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(0.08)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/current_frame.jpg")
def current_frame():
    return Response(analyzer.get_raw_frame_jpeg(), mimetype="image/jpeg")


@app.route("/api/status")
def api_status():
    return jsonify(analyzer.get_metrics())


@app.route("/api/history/latest")
def api_history_latest():
    return jsonify(analyzer.get_latest_history())


@app.route("/api/history")
def api_history():
    try:
        limit = max(10, min(1000, int(request.args.get("limit", 240))))
    except ValueError:
        limit = 240

    rows = read_history_rows(HISTORY_CSV_PATH, limit=limit)
    latest = analyzer.get_latest_history()
    y_max = 0.0
    if rows:
        y_max = max(float(r.get("peak_growth_pct") or 0.0) for r in rows)
        y_max = max(y_max, max(float(r.get("peak_green_coverage_pct") or 0.0) for r in rows))
    current_window = latest.get("current_window") or {}
    y_max = max(y_max, float(current_window.get("peak_growth_pct") or 0.0))
    y_max = max(y_max, float(current_window.get("peak_green_coverage_pct") or 0.0))
    y_max = max(y_max, 1.0)

    return jsonify({
        "rows": rows,
        "count": len(rows),
        "history_save_minutes": int(HISTORY_SAVE_MINUTES),
        "latest_saved": latest.get("latest_saved"),
        "current_window": latest.get("current_window"),
        "y_max": round(float(y_max), 4),
    })


@app.route("/api/history.csv")
def api_history_csv():
    if not HISTORY_CSV_PATH.exists():
        return Response("", mimetype="text/csv")
    return Response(HISTORY_CSV_PATH.read_text(encoding="utf-8"), mimetype="text/csv")


@app.route("/api/roi", methods=["GET", "POST"])
def api_roi():
    if request.method == "GET":
        return jsonify({"points": [{"x": x, "y": y} for x, y in analyzer.get_roi_points()]})

    payload = request.get_json(silent=True) or {}
    raw_points = payload.get("points", [])
    points: List[Tuple[int, int]] = []
    for p in raw_points:
        if isinstance(p, dict):
            points.append((int(p["x"]), int(p["y"])))
        elif isinstance(p, (list, tuple)) and len(p) == 2:
            points.append((int(p[0]), int(p[1])))
    result = analyzer.set_roi(points)
    return jsonify(result)


@app.route("/api/baseline/reset", methods=["POST"])
def api_reset_baseline():
    return jsonify(analyzer.reset_baseline_from_current())


@app.route("/api/config")
def api_config():
    return jsonify({
        "stream_source": STREAM_SOURCE,
        "roi_json_path": str(ROI_JSON_PATH),
        "state_json_path": str(STATE_JSON_PATH),
        "history_csv_path": str(HISTORY_CSV_PATH),
        "history_save_minutes": HISTORY_SAVE_MINUTES,
        "source_mode": analyzer.get_metrics().get("source_mode"),
    })


@app.errorhandler(Exception)
def handle_error(exc):
    return jsonify({"ok": False, "error": str(exc)}), 500


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug, threaded=True)
