"""
Boys Art - Production Flask Server
Hosted on Render: https://boys-art-server.onrender.com
Handles: Activation submissions, approval, template purchases.
"""

import os
import json
import time
import base64
import hashlib
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

ADMIN_SECRET = os.environ.get('ADMIN_SECRET', 'boysart2024master')
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

SUBMISSIONS_FILE = os.path.join(DATA_DIR, 'submissions.json')
PURCHASES_FILE   = os.path.join(DATA_DIR, 'purchases.json')
TEMPLATES_DIR    = os.path.join(DATA_DIR, 'templates')
os.makedirs(TEMPLATES_DIR, exist_ok=True)

_lock = threading.Lock()


# ─────────────────────────── Helpers ────────────────────────────

def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _require_admin(req):
    secret = req.args.get('secret') or (req.json or {}).get('secret', '')
    return secret == ADMIN_SECRET


def _make_id():
    return hashlib.sha256((str(time.time()) + os.urandom(8).hex()).encode()).hexdigest()[:16]


# ─────────────────────────── Health ─────────────────────────────

@app.route('/', methods=['GET'])
@app.route('/api', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'ok': True, 'service': 'Boys Art Server', 'time': time.time()})


# ─────────────────── Activation / Submission ────────────────────

@app.route('/api/activation/submit', methods=['POST'])
def activation_submit():
    body = request.json or {}
    name  = (body.get('name') or '').strip()
    phone = (body.get('phone') or '').strip()
    utr   = (body.get('utrId') or '').strip()

    if not name or not phone or not utr:
        return jsonify({'ok': False, 'error': 'Name, phone, and UTR are required.'}), 400

    with _lock:
        subs = _load_json(SUBMISSIONS_FILE)

        # Check if already exists
        for s in subs:
            if s.get('phone') == phone:
                if s.get('status') == 'approved':
                    return jsonify({'ok': True, 'status': 'approved',
                                    'message': 'Already approved.',
                                    'name': s.get('name', name)})
                # Update UTR if re-submitting
                s['utrId'] = utr
                s['name']  = name
                if s.get('status') == 'rejected':
                    s['status'] = 'pending'
                    s['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                _save_json(SUBMISSIONS_FILE, subs)
                return jsonify({'ok': True, 'status': s['status'],
                                'message': 'Awaiting approval.',
                                'id': s['id']})

        # New submission
        entry = {
            'id':         _make_id(),
            'name':       name,
            'phone':      phone,
            'utrId':      utr,
            'status':     'pending',
            'submitted_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at':   time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        subs.append(entry)
        _save_json(SUBMISSIONS_FILE, subs)

    return jsonify({'ok': True, 'status': 'pending',
                    'message': 'Submitted. Waiting for owner approval.',
                    'id': entry['id']})


@app.route('/api/activation/status/<phone>', methods=['GET'])
def activation_status(phone):
    phone = phone.strip()
    with _lock:
        subs = _load_json(SUBMISSIONS_FILE)
    for s in subs:
        if s.get('phone') == phone:
            return jsonify({'ok': True, 'status': s['status'],
                            'name': s.get('name', ''),
                            'id': s.get('id', '')})
    return jsonify({'ok': False, 'status': 'not_found'})


# ─────────────────────── Admin — Submissions ────────────────────

@app.route('/api/admin/submissions', methods=['GET'])
def admin_get_submissions():
    if not _require_admin(request):
        return jsonify({'error': 'Unauthorized'}), 403
    status_filter = request.args.get('status')
    with _lock:
        subs = _load_json(SUBMISSIONS_FILE)
    if status_filter and status_filter != 'all':
        subs = [s for s in subs if s.get('status') == status_filter]
    subs_sorted = sorted(subs, key=lambda x: x.get('submitted_at', ''), reverse=True)
    return jsonify({'ok': True, 'submissions': subs_sorted})


@app.route('/api/admin/submissions/<sub_id>/approve', methods=['POST'])
def admin_approve_submission(sub_id):
    if not _require_admin(request):
        return jsonify({'error': 'Unauthorized'}), 403
    with _lock:
        subs = _load_json(SUBMISSIONS_FILE)
        for s in subs:
            if s.get('id') == sub_id:
                s['status'] = 'approved'
                s['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                _save_json(SUBMISSIONS_FILE, subs)
                return jsonify({'ok': True, 'message': f"Approved {s.get('name', sub_id)}"})
    return jsonify({'ok': False, 'error': 'Submission not found'}), 404


@app.route('/api/admin/submissions/<sub_id>/reject', methods=['POST'])
def admin_reject_submission(sub_id):
    if not _require_admin(request):
        return jsonify({'error': 'Unauthorized'}), 403
    with _lock:
        subs = _load_json(SUBMISSIONS_FILE)
        for s in subs:
            if s.get('id') == sub_id:
                s['status'] = 'rejected'
                s['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                _save_json(SUBMISSIONS_FILE, subs)
                return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Not found'}), 404


# ─────────────────────── Template Purchases ─────────────────────

@app.route('/api/purchases/submit', methods=['POST'])
def purchase_submit():
    body = request.json or {}
    phone    = (body.get('phone') or '').strip()
    name     = (body.get('name') or '').strip()
    utr      = (body.get('utrId') or '').strip()
    brand    = (body.get('brand') or '').strip()
    model    = (body.get('model') or '').strip()
    template = (body.get('template') or '').strip()
    amount   = body.get('amount', 0)

    if not phone or not utr or not brand or not model:
        return jsonify({'ok': False, 'error': 'Missing required fields.'}), 400

    with _lock:
        purchases = _load_json(PURCHASES_FILE)
        entry = {
            'id':          _make_id(),
            'phone':       phone,
            'name':        name,
            'utrId':       utr,
            'brand':       brand,
            'model':       model,
            'template':    template,
            'amount':      amount,
            'status':      'pending',
            'submitted_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at':   time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        purchases.append(entry)
        _save_json(PURCHASES_FILE, purchases)

    return jsonify({'ok': True, 'status': 'pending',
                    'message': 'Purchase submitted. Awaiting owner approval.',
                    'id': entry['id']})


@app.route('/api/purchases/status/<phone>', methods=['GET'])
def purchase_status(phone):
    with _lock:
        purchases = _load_json(PURCHASES_FILE)
    user_purchases = [p for p in purchases if p.get('phone') == phone.strip()]
    return jsonify({'ok': True, 'purchases': user_purchases})


@app.route('/api/admin/purchases', methods=['GET'])
def admin_get_purchases():
    if not _require_admin(request):
        return jsonify({'error': 'Unauthorized'}), 403
    status_filter = request.args.get('status')
    with _lock:
        purchases = _load_json(PURCHASES_FILE)
    if status_filter and status_filter != 'all':
        purchases = [p for p in purchases if p.get('status') == status_filter]
    purchases_sorted = sorted(purchases, key=lambda x: x.get('submitted_at', ''), reverse=True)
    return jsonify({'ok': True, 'purchases': purchases_sorted})


@app.route('/api/admin/purchases/<purchase_id>/approve', methods=['POST'])
def admin_approve_purchase(purchase_id):
    if not _require_admin(request):
        return jsonify({'error': 'Unauthorized'}), 403
    with _lock:
        purchases = _load_json(PURCHASES_FILE)
        for p in purchases:
            if p.get('id') == purchase_id:
                p['status'] = 'approved'
                p['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                _save_json(PURCHASES_FILE, purchases)
                return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Not found'}), 404


@app.route('/api/admin/purchases/<purchase_id>/reject', methods=['POST'])
def admin_reject_purchase(purchase_id):
    if not _require_admin(request):
        return jsonify({'error': 'Unauthorized'}), 403
    with _lock:
        purchases = _load_json(PURCHASES_FILE)
        for p in purchases:
            if p.get('id') == purchase_id:
                p['status'] = 'rejected'
                p['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                _save_json(PURCHASES_FILE, purchases)
                return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Not found'}), 404


# ─────────────────── Template Upload (Master) ───────────────────

@app.route('/api/admin/upload-template', methods=['POST'])
def admin_upload_template():
    if not _require_admin(request):
        return jsonify({'error': 'Unauthorized'}), 403
    body = request.json or {}
    rel_path = (body.get('path') or '').strip()
    data_b64 = body.get('data', '')
    if not rel_path or not data_b64:
        return jsonify({'ok': False, 'error': 'path and data are required'}), 400

    # Sanitize path
    rel_path = rel_path.replace('\\', '/').lstrip('/')
    out_path = os.path.join(TEMPLATES_DIR, rel_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        file_bytes = base64.b64decode(data_b64)
        with open(out_path, 'wb') as f:
            f.write(file_bytes)
        return jsonify({'ok': True, 'path': rel_path})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/templates/list', methods=['GET'])
def list_templates():
    result = []
    for root, dirs, files in os.walk(TEMPLATES_DIR):
        for fname in files:
            if fname.lower().endswith('.dxf'):
                rel = os.path.relpath(os.path.join(root, fname), TEMPLATES_DIR)
                result.append(rel.replace('\\', '/'))
    return jsonify({'ok': True, 'templates': sorted(result)})


@app.route('/api/templates/download', methods=['GET'])
def download_template():
    rel_path = request.args.get('path', '').strip().lstrip('/')
    if not rel_path:
        return jsonify({'error': 'path is required'}), 400
    file_path = os.path.join(TEMPLATES_DIR, rel_path)
    if not os.path.exists(file_path):
        return jsonify({'error': 'Template not found'}), 404
    with open(file_path, 'rb') as f:
        data = f.read()
    return jsonify({'ok': True, 'path': rel_path,
                    'data': base64.b64encode(data).decode('utf-8')})


# ─────────────────────────── Run ────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
