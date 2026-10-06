"""Person detection in listing photos (OpenCV DNN, MobileNet-SSD Caffe).

Razi's rule: listing photos must show the EMPTY property only — no people
(men, women, children) visible in the photo. When a person is detected, the
photo is auto-rejected (photo_status='rejected', photo_flag='person_detected')
and the landlord sees an Urdu reason on their dashboard; the listing stays
hidden until a clean photo is uploaded. No admin action is needed.

Detection thresholds (tuned for property photos):
- CONFIDENCE_THRESHOLD = 0.5 — minimum MobileNet-SSD confidence for the
  'person' class (class id 15).
- MIN_BOX_AREA_RATIO = 0.02 — detections whose bounding box covers less than
  2% of the image area are ignored (tiny background figures / false
  positives on posters, statues, etc.).

Fail-open: if OpenCV is not installed, or the model files cannot be
downloaded/loaded, every check returns "no person" (with a warning log) and
photo uploads proceed normally. The guard must NEVER break uploads.

Model files (~23MB) are downloaded once from GitHub into app/data/models/
on first use and cached there afterwards.
"""
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

# --- detection thresholds (documented, see module docstring) ---
CONFIDENCE_THRESHOLD = 0.5
MIN_BOX_AREA_RATIO = 0.02
PERSON_CLASS_ID = 15  # 'person' in the MobileNet-SSD Caffe label set

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "models")
PROTOTXT_URL = ("https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD"
                "/master/deploy.prototxt")
CAFFEMODEL_URL = ("https://github.com/chuanqi305/MobileNet-SSD"
                  "/raw/master/mobilenet_iter_73000.caffemodel")
PROTOTXT_PATH = os.path.join(MODEL_DIR, "mobilenet_ssd_deploy.prototxt")
CAFFEMODEL_PATH = os.path.join(MODEL_DIR, "mobilenet_ssd.caffemodel")

_net = None  # cached DNN net


def _download(url, dest, timeout=60):
    """Download url -> dest (cached: skip when dest already exists)."""
    if os.path.isfile(dest):
        return True
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KirayaNama/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
                open(tmp, "wb") as fh:
            shutil_copy(resp, fh)
        os.replace(tmp, dest)
        log.info("person_guard: downloaded model file %s", dest)
        return True
    except Exception as exc:  # noqa: BLE001 - fail open, never break uploads
        log.warning("person_guard: model download failed (%s): %s", url, exc)
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def shutil_copy(resp, fh, chunk=1024 * 64):
    while True:
        data = resp.read(chunk)
        if not data:
            break
        fh.write(data)


def model_available():
    """True when both model files exist locally (downloads them on first use).

    Returns False (with a warning log) when the download fails — callers
    must treat that as "no person detected" (fail open).
    """
    if os.path.isfile(PROTOTXT_PATH) and os.path.isfile(CAFFEMODEL_PATH):
        return True
    ok_proto = _download(PROTOTXT_URL, PROTOTXT_PATH)
    ok_model = _download(CAFFEMODEL_URL, CAFFEMODEL_PATH)
    if not (ok_proto and ok_model):
        log.warning("person_guard: model unavailable — person check skipped "
                    "(fail open)")
        return False
    return True


def _get_net():
    """Return the cached DNN net, or None when OpenCV/model is unavailable."""
    global _net
    if _net is not None:
        return _net
    try:
        import cv2
    except ImportError:
        log.warning("person_guard: opencv not installed — skipping person "
                    "check (fail open)")
        return None
    if not model_available():
        return None
    try:
        _net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, CAFFEMODEL_PATH)
        log.info("person_guard: MobileNet-SSD model loaded")
        return _net
    except Exception as exc:  # noqa: BLE001 - fail open
        log.warning("person_guard: could not load DNN model: %s (fail open)",
                    exc)
        return None


def _is_valid_detection(confidence, area_ratio):
    """Pure threshold check (no OpenCV needed): confidence >= 0.5 AND the
    bounding box covers >= 2% of the image area."""
    return (confidence >= CONFIDENCE_THRESHOLD
            and area_ratio >= MIN_BOX_AREA_RATIO)


def _person_boxes(net, image_path):
    """Return list of (confidence, area_ratio) for person-class detections
    that pass the confidence threshold (area filtering happens in
    _is_valid_detection so it stays unit-testable)."""
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        log.warning("person_guard: cannot read image %s", image_path)
        return []
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return []
    blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)),
                                 0.007843, (300, 300), 127.5)
    net.setInput(blob)
    detections = net.forward()
    hits = []
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        class_id = int(detections[0, 0, i, 1])
        if class_id != PERSON_CLASS_ID or confidence < CONFIDENCE_THRESHOLD:
            continue
        box = detections[0, 0, i, 3:7] * [w, h, w, h]
        x1, y1, x2, y2 = box.astype(int)
        area_ratio = max(0, x2 - x1) * max(0, y2 - y1) / float(w * h)
        hits.append((confidence, area_ratio))
    return hits


def person_detected_in_image(image_path):
    """True when a person is detected in the photo, else False.

    Fail-open: returns False (with a warning log) when OpenCV or the model
    is unavailable, or when anything goes wrong. Never raises.
    """
    try:
        net = _get_net()
        if net is None:
            return False
        for confidence, area_ratio in _person_boxes(net, image_path):
            if _is_valid_detection(confidence, area_ratio):
                log.warning("person_guard: person detected in %s "
                            "(conf=%.2f, area=%.1f%%)",
                            image_path, confidence, area_ratio * 100)
                return True
        return False
    except Exception as exc:  # noqa: BLE001 - guard must never break uploads
        log.warning("person_guard: detection crashed for %s: %s (fail open)",
                    image_path, exc)
        return False


def scan_photo_paths(paths):
    """Scan saved photo files; True when ANY photo shows a person.

    Never raises — returns False on any failure (fail open).
    """
    try:
        for p in paths:
            if not p or not os.path.isfile(p):
                continue
            if person_detected_in_image(p):
                return True
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("person_guard: scan crashed: %s (fail open)", exc)
        return False
