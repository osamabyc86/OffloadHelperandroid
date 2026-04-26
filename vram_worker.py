#!/usr/bin/env python3
"""
VRAM Worker - متكامل مع peer_discovery.py (نفس نظام main.py)
"""

import os
import sys
import time
import socket
import threading
import base64
import json
from flask import Flask, request, jsonify
from flask_cors import CORS

# استيراد نظام الاكتشاف من main.py
sys.path.insert(0, os.path.dirname(__file__))
from peer_discovery import discovery_manager, CAP_TENSOR_STORAGE, CAP_KV_CACHE, CAP_CPU_INFERENCE

VRAM_WORKER_PORT = 7520  # نفس منفذ main.py
TENSOR_STORE_MAX_MB = 3500

# التخزين المحلي
tensor_store = {}
kv_cache_store = {}
stats = {
    "tensors_stored": 0,
    "total_bytes": 0,
    "requests_served": 0,
    "start_time": time.time()
}

app = Flask(__name__)
CORS(app)

# ============================================================
# نقاط النهاية (Endpoints)
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    """نقطة نهاية للصحة - متوافقة مع نظام الاكتشاف"""
    return jsonify({
        "status": "healthy",
        "role": "vram_worker",
        "port": VRAM_WORKER_PORT,
        "capabilities": [CAP_TENSOR_STORAGE, CAP_KV_CACHE, CAP_CPU_INFERENCE],
        "stats": {
            "tensors": stats["tensors_stored"],
            "total_mb": stats["total_bytes"] / (1024 * 1024),
            "max_mb": TENSOR_STORE_MAX_MB,
            "requests": stats["requests_served"]
        }
    })

@app.route("/api/capabilities", methods=["GET"])
def get_capabilities():
    return jsonify({
        "node_type": "vram_worker",
        "capabilities": [CAP_TENSOR_STORAGE, CAP_KV_CACHE, CAP_CPU_INFERENCE],
        "max_ram_mb": TENSOR_STORE_MAX_MB,
        "current_usage_mb": stats["total_bytes"] / (1024 * 1024),
        "port": VRAM_WORKER_PORT
    })

@app.route("/tensor/store", methods=["POST"])
def store_tensor():
    try:
        data = request.get_json()
        name = data.get("name")
        tensor_data_b64 = data.get("data")
        
        if not name or not tensor_data_b64:
            return jsonify({"error": "name and data required"}), 400
        
        tensor_bytes = base64.b64decode(tensor_data_b64)
        tensor_store[name] = tensor_bytes
        
        stats["tensors_stored"] += 1
        stats["total_bytes"] += len(tensor_bytes)
        
        return jsonify({
            "status": "ok",
            "name": name,
            "size_mb": len(tensor_bytes) / (1024 * 1024)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/tensor/fetch/<name>", methods=["GET"])
def fetch_tensor(name):
    try:
        if name in tensor_store:
            stats["requests_served"] += 1
            return jsonify({
                "name": name,
                "data": base64.b64encode(tensor_store[name]).decode('ascii'),
                "size_bytes": len(tensor_store[name])
            })
        return jsonify({"error": "not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/tensor/list", methods=["GET"])
def list_tensors():
    return jsonify({
        "tensors": list(tensor_store.keys()),
        "count": len(tensor_store),
        "total_mb": stats["total_bytes"] / (1024 * 1024),
        "stats": stats
    })

@app.route("/kv/store", methods=["POST"])
def kv_store():
    try:
        data = request.get_json()
        seq_id = data.get("seq_id")
        layer = data.get("layer")
        k_b64 = data.get("k")
        v_b64 = data.get("v")
        
        if not all([seq_id, layer is not None, k_b64, v_b64]):
            return jsonify({"error": "seq_id, layer, k, v required"}), 400
        
        key = f"{seq_id}_{layer}"
        kv_cache_store[key] = (k_b64, v_b64)
        
        return jsonify({"status": "ok", "key": key})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/kv/fetch", methods=["GET"])
def kv_fetch():
    seq_id = request.args.get("seq_id")
    layer = request.args.get("layer")
    
    if not seq_id or layer is None:
        return jsonify({"error": "seq_id and layer required"}), 400
    
    key = f"{seq_id}_{layer}"
    
    if key in kv_cache_store:
        k, v = kv_cache_store[key]
        return jsonify({
            "seq_id": seq_id,
            "layer": int(layer),
            "k": k,
            "v": v
        })
    return jsonify({"error": "not found"}), 404

# ============================================================
# التشغيل الرئيسي
# ============================================================

def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

def register_self():
    """تسجيل النفس في نظام peer_discovery"""
    try:
        local_ip = get_local_ip()
        peer_data = {
            "ip": local_ip,
            "port": VRAM_WORKER_PORT,
            "hostname": socket.gethostname(),
            "capabilities": [CAP_TENSOR_STORAGE, CAP_KV_CACHE, CAP_CPU_INFERENCE],
            "max_ram_mb": TENSOR_STORE_MAX_MB
        }
        discovery_manager.add_peer_from_discovery_enhanced(peer_data, "vram_worker")
        print(f"✅ تم التسجيل في نظام الاكتشاف: {local_ip}:{VRAM_WORKER_PORT}")
        return True
    except Exception as e:
        print(f"⚠️ فشل التسجيل: {e}")
        return False

def main():
    print("=" * 60)
    print("🧠 VRAM Worker - متكامل مع peer_discovery")
    print("=" * 60)
    print(f"📦 الحد الأقصى للذاكرة: {TENSOR_STORE_MAX_MB}MB")
    print(f"🔌 المنفذ: {VRAM_WORKER_PORT}")
    print("=" * 60)
    
    # بدء نظام الاكتشاف (نفس نظام main.py)
    try:
        discovery_manager.start_enhanced_discovery()
        print("✅ نظام discovery_manager يعمل")
    except Exception as e:
        print(f"⚠️ فشل بدء discovery_manager: {e}")
    
    # تسجيل النفس
    register_self()
    
    # عرض الأقران المكتشفين
    print(f"🔍 الأقران النشطون حالياً: {len(discovery_manager.get_active_peers())}")
    
    # تشغيل خادم Flask
    print(f"\n🚀 تشغيل خادم VRAM Worker على المنفذ {VRAM_WORKER_PORT}")
    print(f"📡 متاح على: http://{get_local_ip()}:{VRAM_WORKER_PORT}")
    print("=" * 60)
    
    try:
        app.run(host="0.0.0.0", port=VRAM_WORKER_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n🛑 إيقاف الخادم...")
        discovery_manager.stop()

if __name__ == "__main__":
    main()
