import json
import os
import shutil
import uuid

from flask import Flask, jsonify, render_template, request

from services.extractor import extract_fields
from services.ocr import refine_masked_text, run_ocr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
DEBUG_DIR = os.path.join(BASE_DIR, 'debug_ocr')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
DEBUG_OCR = os.environ.get('DEBUG_OCR') == '1'

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB

os.makedirs(UPLOAD_DIR, exist_ok=True)


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/extract', methods=['POST'])
def extract():
    file = request.files.get('receipt')

    if file is None or file.filename == '':
        return jsonify({'error': 'No image was uploaded.'}), 400

    if not _allowed_file(file.filename):
        return jsonify({'error': 'Unsupported file type. Please upload a PNG or JPG image.'}), 400

    temp_path = os.path.join(UPLOAD_DIR, f'{uuid.uuid4().hex}.tmp')
    file.save(temp_path)

    try:
        try:
            lines, ocr_image = run_ocr(temp_path)
        except Exception:
            return jsonify({'error': 'This image could not be processed. Please try a different receipt image.'}), 422

        if not lines:
            return jsonify({'error': 'No text could be detected in this image. Please try a clearer photo of the receipt.'}), 422

        fields, name_line = extract_fields(lines)

        if fields.get('name') and name_line:
            try:
                fields['name'] = refine_masked_text(ocr_image, name_line)
            except Exception:
                pass  # fall back to the original OCR'd name rather than fail the whole request

        if DEBUG_OCR:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            ext = file.filename.rsplit('.', 1)[1].lower()
            shutil.copyfile(temp_path, os.path.join(DEBUG_DIR, f'last_receipt.{ext}'))
            with open(os.path.join(DEBUG_DIR, 'last_ocr_lines.json'), 'w') as f:
                json.dump(lines, f, indent=2)
            with open(os.path.join(DEBUG_DIR, 'last_fields.json'), 'w') as f:
                json.dump(fields, f, indent=2)

        if not any(fields.values()):
            return jsonify({
                'error': 'Could not confidently detect any receipt details. Please try a clearer image.',
            }), 422

        return jsonify({'fields': fields})
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
