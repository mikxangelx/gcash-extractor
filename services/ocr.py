"""Tesseract OCR wrapper. OCR runs fully locally — no image or text ever leaves the machine."""

import cv2
import pytesseract
from pytesseract import Output

TESSERACT_CONFIG = '--oem 3 --psm 6'


def _load_image(image_path):
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError('Could not read image file.')

    height, width = image.shape[:2]
    min_dim = min(height, width)
    if min_dim < 1000:
        scale = 1000 / min_dim
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return gray


def _group_words_into_lines(data):
    """Groups Tesseract's word-level output into line-level entries keyed by
    (block, paragraph, line), matching the granularity the field extractor expects."""
    grouped = {}
    n = len(data['text'])

    for i in range(n):
        word = data['text'][i].strip()
        conf = float(data['conf'][i])
        if not word or conf < 0:
            continue

        key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        left, top = data['left'][i], data['top'][i]
        right, bottom = left + data['width'][i], top + data['height'][i]

        if key not in grouped:
            grouped[key] = {
                'words': [],
                'confidences': [],
                'left': left, 'top': top, 'right': right, 'bottom': bottom,
            }

        entry = grouped[key]
        entry['words'].append(word)
        entry['confidences'].append(conf)
        entry['left'] = min(entry['left'], left)
        entry['top'] = min(entry['top'], top)
        entry['right'] = max(entry['right'], right)
        entry['bottom'] = max(entry['bottom'], bottom)

    lines = []
    for entry in grouped.values():
        text = ' '.join(entry['words']).strip()
        if not text:
            continue
        lines.append({
            'text': text,
            'confidence': (sum(entry['confidences']) / len(entry['confidences'])) / 100.0,
            'top': entry['top'],
            'bottom': entry['bottom'],
            'left': entry['left'],
            'right': entry['right'],
            'height': entry['bottom'] - entry['top'],
            'center_x': (entry['left'] + entry['right']) / 2,
            'center_y': (entry['top'] + entry['bottom']) / 2,
        })

    lines.sort(key=lambda l: (round(l['center_y'] / 15), l['center_x']))
    return lines


def run_ocr(image_path):
    """Runs OCR on the given image path and returns (lines, image).

    Each line is a dict: {text, confidence, top, left, right, bottom, height, center_x, center_y}
    where coordinates are in pixels, grouped from Tesseract's word-level output.
    The preprocessed image is returned too so a caller can re-inspect a specific
    line (e.g. to tell real letters apart from GCash's masking dots).
    """
    image = _load_image(image_path)
    data = pytesseract.image_to_data(image, config=TESSERACT_CONFIG, output_type=Output.DICT)
    return _group_words_into_lines(data), image


def refine_masked_text(image, line, mask_char='*'):
    """Tells real letters apart from GCash's small round privacy-masking dots
    within one already-recognized line.

    Tesseract's word-level pass has no concept of "this glyph isn't a letter" —
    it always guesses the closest-looking character (a masking dot commonly
    comes out as 'e' or 'o'). This pairs the already-recognized text with each
    glyph's own bounding box (found independently via contour detection, since
    re-running Tesseract on a tiny crop introduces its own segmentation noise)
    and flags glyphs that are short, roughly round, and vertically centered —
    unlike full-height letters or baseline-sitting punctuation like a period.
    The comparison is against the *other* glyphs on that same line, so it's
    self-calibrating per line rather than tied to any specific name or font.
    If the glyph count doesn't cleanly match the character count, the original
    OCR'd text is returned unchanged — nothing is invented either way.
    """
    pad = 4
    top = max(int(line['top']) - pad, 0)
    bottom = int(line['bottom']) + pad
    left = max(int(line['left']) - pad, 0)
    right = int(line['right']) + pad
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        return line['text']

    crop_height = crop.shape[0]
    inverted = cv2.bitwise_not(crop)
    contours, _ = cv2.findContours(inverted, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours]
    boxes = [b for b in boxes if b[2] * b[3] >= 10]
    boxes.sort(key=lambda b: b[0])

    text = line['text']
    non_space_chars = [ch for ch in text if not ch.isspace()]

    if len(boxes) < 3 or len(boxes) != len(non_space_chars):
        return text  # can't reliably pair glyphs to characters; leave as-is

    reference_height = max(h for (_, _, _, h) in boxes)
    if reference_height <= 0:
        return text

    refined = []
    for ch, (_, y, w, h) in zip(non_space_chars, boxes):
        height_ratio = h / reference_height
        y_center_ratio = (y + h / 2) / crop_height
        aspect = w / h if h else 0
        is_masking_dot = (
            ch.isalpha()
            and 0.15 <= height_ratio <= 0.42
            and 0.7 <= aspect <= 1.4
            and y_center_ratio <= 0.72
        )
        refined.append(mask_char if is_masking_dot else ch)

    result, it = [], iter(refined)
    for ch in text:
        result.append(ch if ch.isspace() else next(it))

    return ''.join(result).strip() or text
