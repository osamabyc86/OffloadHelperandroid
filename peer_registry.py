#!/usr/bin/env python3
"""
VRAM Worker - متكامل مع نظام peer_registry.py
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

# استيراد نظام التسجيل الموحد
from peer_registry import registry

VRAM_WORKER_PORT = 72500
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
        "node_id": registry.node_id,
        "stats": {
            "tensors": stats["tensors_stored"],
            "total_mb": stats["total_bytes"] / (1024 * 1024),
            "max_mb": TENSOR_STORE_MAX_MB,
            "requests": stats["requests_served"]
        },
        "capabilities": ["tensor_storage", "kv_cache", "cpu_inference"]
    })

@app.route("/api/capabilities", methods=["GET"])
def get_capabilities():
    """إعلان قدرات هذا الجهاز"""
    return jsonify({
        "node_type": "vram_worker",
        "capabilities": ["tensor_storage", "kv_cache", "cpu_inference"],
        "max_ram_mb": TENSOR_STORE_MAX_MB,
        "current_usage_mb": stats["total_bytes"] / (1024 * 1024),
        "port": VRAM_WORKER_PORT,
        "node_id": registry.node_id
    })

@app.route("/tensor/store", methods=["POST"])
def store_tensor():
    """تخزين tensor"""
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
    """استرجاع tensor"""
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
    """قائمة جميع الـ tensors"""
    return jsonify({
        "tensors": list(tensor_store.keys()),
        "count": len(tensor_store),
        "total_mb": stats["total_bytes"] / (1024 * 1024),
        "stats": stats
    })

@app.route("/kv/store", methods=["POST"])
def kv_store():
    """تخزين KV cache"""
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
    """استرجاع KV cache"""
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
    """الحصول على IP المحلي"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

def main():
    print("=" * 60)
    print("🧠 VRAM Worker - متكامل مع peer_registry")
    print("=" * 60)
    print(f"📦 الحد الأقصى للذاكرة: {TENSOR_STORE_MAX_MB}MB")
    print(f"🔌 المنفذ: {VRAM_WORKER_PORT}")
    print(f"🆔 معرف العقدة: {registry.node_id}")
    print("=" * 60)
    
    # بدء نظام التسجيل والاكتشاف الموحد
    print("🔄 بدء نظام التسجيل...")
    if registry.start():
        print("✅ تم تسجيل الخدمة في الشبكة")
        print(f"📍 IP المحلي: {registry.local_ip}")
        print(f"🔍 الأقران المكتشفون حالياً: {len(registry.get_active_peers())}")
    else:
        print("⚠️ فشل في تسجيل الخدمة، لكن الخادم سيعمل")
    
    # تشغيل خادم Flask
    print(f"\n🚀 تشغيل خادم VRAM Worker على المنفذ {VRAM_WORKER_PORT}")
    print(f"📡 متاح على: http://{get_local_ip()}:{VRAM_WORKER_PORT}")
    print("=" * 60)
    
    try:
        app.run(host="0.0.0.0", port=VRAM_WORKER_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n🛑 إيقاف الخادم...")
    finally:
        registry.stop()
        print("✅ تم إيقاف النظام")

if __name__ == "__main__":
    main()
