"""Targeted field extraction from OCR'd GCash receipt lines.

Uses text pattern matching plus the spatial position of each detected line
(as provided by PaddleOCR) to pick out six fields: name, mobile number,
reference number, date, time, and total amount sent. Nothing is hardcoded
to a specific receipt — every value is derived from regex + label/position
heuristics that should generalize across similar GCash receipt layouts.
"""

import re

MOBILE_RE = re.compile(r'(?:\+?63[\s\-]?|0)9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}')

REFERENCE_LABEL_RE = re.compile(r'ref(?:erence)?\.?\s*(?:no\.?|number)?', re.IGNORECASE)
REFERENCE_VALUE_RE = re.compile(r'\b\d[\d\s\-]{8,17}\d\b')

AMOUNT_RE = re.compile(r'(?:₱|PHP|Php|P)\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?')
AMOUNT_LABEL_RE = re.compile(r'(total amount|amount sent|you\s*sent|amount)', re.IGNORECASE)

TIME_RE = re.compile(r'\b\d{1,2}:\d{2}\s?(?:[AaPp]\.?[Mm]\.?)?\b')

MONTHS = (
    'january|february|march|april|may|june|july|august|september|october|november|december|'
    'jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec'
)
DATE_RE_LIST = [
    re.compile(rf'\b(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}}\b', re.IGNORECASE),
    re.compile(rf'\b\d{{1,2}}\s+(?:{MONTHS})\.?\s+\d{{4}}\b', re.IGNORECASE),
    re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
    re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'),
]

NAME_STOPWORDS = {
    'gcash', 'send money', 'successful', 'total amount', 'reference no',
    'reference number', 'amount', 'mobile number', 'date', 'time', 'done',
    'share', 'save', 'help', 'terms', 'conditions', 'padala', 'cash in',
    'cash out', 'pay bills', 'buy load', 'send', 'money', 'to', 'from',
    'account', 'wallet', 'ref', 'no', 'number', 'details', 'transaction',
    'receipt', 'transfer', 'load', 'bills', 'payment', 'pending', 'failed',
    'express send', 'bank transfer',
}
NAME_CANDIDATE_RE = re.compile(r"^[A-Za-z.\-'ñÑ*]+(?:\s+[A-Za-z.\-'ñÑ*]+){1,3}$")
NAME_STOPWORD_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(w) for w in sorted(NAME_STOPWORDS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)


def _full_text(lines):
    return '\n'.join(l['text'] for l in lines)


def _find_regex_anywhere(lines, pattern):
    for line in lines:
        match = pattern.search(line['text'])
        if match:
            return match.group().strip(), line
    return None, None


def _nearby_lines(lines, anchor, max_vertical_gap=60):
    """Lines below/around the anchor line, ordered by proximity, for label->value search."""
    anchor_bottom = anchor['bottom']
    anchor_cy = anchor['center_y']
    candidates = [
        l for l in lines
        if l is not anchor and 0 <= (l['top'] - anchor_bottom) <= max_vertical_gap
    ]
    same_line = [
        l for l in lines
        if l is not anchor and abs(l['center_y'] - anchor_cy) < (anchor['height'] / 2 + 5)
        and l['left'] > anchor['left']
    ]
    return same_line + sorted(candidates, key=lambda l: l['top'])


def _normalize_mobile_number(raw):
    """Strips all formatting, folds the +63/63 country code back to a leading 0,
    and renders the canonical 0XXX XXX XXXX display format."""
    digits = re.sub(r'\D', '', raw)

    if digits.startswith('63') and len(digits) == 12:
        digits = '0' + digits[2:]

    if len(digits) == 11 and digits.startswith('0'):
        return f'{digits[:4]} {digits[4:7]} {digits[7:]}'

    return digits


def extract_mobile_number(lines):
    value, line = _find_regex_anywhere(lines, MOBILE_RE)
    if value:
        return _normalize_mobile_number(value), line
    return None, None


def extract_reference_number(lines, exclude_texts=()):
    for line in lines:
        if not REFERENCE_LABEL_RE.search(line['text']):
            continue

        same_line_after_label = REFERENCE_LABEL_RE.sub('', line['text'], count=1)
        match = REFERENCE_VALUE_RE.search(same_line_after_label)
        if match:
            candidate = match.group().strip()
            if candidate not in exclude_texts:
                return re.sub(r'[\s\-]', '', candidate), line

        for nearby in _nearby_lines(lines, line):
            if nearby['text'].strip() in exclude_texts:
                continue
            match = REFERENCE_VALUE_RE.search(nearby['text'])
            if match:
                return re.sub(r'[\s\-]', '', match.group().strip()), nearby

    return None, None


def extract_date(lines):
    for pattern in DATE_RE_LIST:
        value, line = _find_regex_anywhere(lines, pattern)
        if value:
            return value.strip(), line
    return None, None


def extract_time(lines):
    for line in lines:
        match = TIME_RE.search(line['text'])
        if match:
            return match.group().strip().upper().replace('.', ''), line
    return None, None


def extract_total_amount(lines):
    labeled_candidates = []
    all_candidates = []

    for line in lines:
        for match in AMOUNT_RE.finditer(line['text']):
            candidate = (match.group().strip(), line)
            all_candidates.append(candidate)
            if AMOUNT_LABEL_RE.search(line['text']):
                labeled_candidates.append(candidate)
            else:
                for nearby in _nearby_lines(lines, line, max_vertical_gap=50):
                    if AMOUNT_LABEL_RE.search(nearby['text']):
                        labeled_candidates.append(candidate)
                        break

    pool = labeled_candidates or all_candidates
    if not pool:
        return None, None

    value, line = max(pool, key=lambda c: c[1]['height'])
    number_part = re.sub(r'^(?:₱|PHP|Php|P)\s?', '', value)
    return '₱' + number_part, line


def _normalize_name(raw):
    """Trims whitespace only. Masking asterisks are part of what GCash actually
    shows on the receipt and are preserved as-is — never stripped or guessed at."""
    return re.sub(r'\s{2,}', ' ', raw).strip()


def extract_name(lines, mobile_line):
    def candidate_name(line):
        text = line['text'].strip()
        lowered = text.lower()
        if any(ch.isdigit() for ch in text):
            return None
        if '₱' in text or 'php' in lowered:
            return None
        if not NAME_CANDIDATE_RE.match(text):
            return None
        if NAME_STOPWORD_RE.search(text):
            return None
        return _normalize_name(text) or None

    if mobile_line:
        nearby = [
            l for l in lines
            if l is not mobile_line and abs(l['center_y'] - mobile_line['center_y']) < 200
        ]
        nearby.sort(key=lambda l: abs(l['top'] - mobile_line['top']))
        for line in nearby:
            name = candidate_name(line)
            if name:
                return name, line

    for line in lines:
        name = candidate_name(line)
        if name:
            return name, line

    return None, None


def extract_fields(lines):
    """Runs all six field extractors and returns (fields, name_line).

    fields is a plain dict of results — any field that cannot be confidently
    identified is returned as None, and the caller/UI is responsible for
    rendering that as "Not detected". Nothing is guessed or invented.

    name_line is the raw OCR line the name came from (or None), returned so
    the caller can optionally re-inspect that specific region of the image —
    e.g. to tell real letters apart from GCash's privacy-masking dots.
    """
    mobile_number, mobile_line = extract_mobile_number(lines)
    reference_number, _ = extract_reference_number(
        lines, exclude_texts={mobile_number} if mobile_number else set()
    )
    date, _ = extract_date(lines)
    time, _ = extract_time(lines)
    total_amount, _ = extract_total_amount(lines)
    name, name_line = extract_name(lines, mobile_line)

    fields = {
        'name': name,
        'mobile_number': mobile_number,
        'reference_number': reference_number,
        'date': date,
        'time': time,
        'total_amount': total_amount,
    }
    return fields, name_line
