#!/usr/bin/env python3
import os
import socket
import threading
import time
import logging
from typing import Optional, Set, Dict, Any
import json
import requests
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, NonUniqueNameException

# Configurations
SERVICE_TYPE = "_tasknode._tcp.local."
PORT = int(os.getenv("PEER_PORT", "7520"))
CENTRAL_REGISTRY_URL = "https://cv4790811.regru.cloud"
HEARTBEAT_INTERVAL = 60  # seconds

class PeerDiscovery:
    def __init__(self):
        self.peers: Set[str] = set()
        self.zeroconf = None
        self.logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("PeerDiscovery")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def get_local_ip(self) -> str:
        """Get the most appropriate IP address"""
        try:
            # Try public IP first
            try:
                resp = requests.get("https://api.ipify.org?format=json", timeout=3)
                if resp.status_code == 200:
                    return resp.json().get("ip", "127.0.0.1")
            except:
                pass
            
            # Fallback to local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def register_service(self, port: int = PORT, service_name: Optional[str] = None) -> bool:
        """Register this service on the local network"""
        try:
            hostname = socket.gethostname()
            local_ip = self.get_local_ip()
            
            if not service_name:
                service_name = f"tasknode_{hostname}_{port}"
            
            service_info = ServiceInfo(
                SERVICE_TYPE,
                f"{service_name}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(local_ip)],
                port=port,
                properties={
                    'version': '1.0',
                    'hostname': hostname,
                    'ip': local_ip,
                    'load': '0'
                },
                server=f"{hostname}.local."
            )
            
            self.zeroconf = Zeroconf()
            self.zeroconf.register_service(service_info)
            self.logger.info(f"Service registered: {service_name} @ {local_ip}:{port}")
            return True
            
        except NonUniqueNameException:
            new_name = f"{service_name}_{int(time.time())}"
            self.logger.warning(f"Duplicate name, using new name: {new_name}")
            return self.register_service(port, new_name)
            
        except Exception as e:
            self.logger.error(f"Service registration failed: {str(e)}")
            return False

    def discover_peers(self) -> None:
        """Discover peers on local network"""
        class PeerListener:
            def __init__(self, outer):
                self.outer = outer
            
            def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                info = zc.get_service_info(type_, name)
                if info and info.addresses:
                    ip = socket.inet_ntoa(info.addresses[0])
                    peer_url = f"http://{ip}:{info.port}/run"
                    if peer_url not in self.outer.peers:
                        self.outer.peers.add(peer_url)
                        self.outer.logger.info(f"Discovered LAN peer: {peer_url}")

            def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                self.add_service(zc, type_, name)

            def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                self.outer.logger.info(f"Peer removed: {name}")

        browser = ServiceBrowser(self.zeroconf, SERVICE_TYPE, PeerListener(self))
        self.logger.info(f"Starting LAN discovery for {SERVICE_TYPE}")

    def register_with_central(self) -> bool:
        """Register with central registry"""
        try:
            node_info = {
                "node_id": os.getenv("NODE_ID", socket.gethostname()),
                "ip": self.get_local_ip(),
                "port": PORT,
                "last_seen": int(time.time())
            }
            
            resp = requests.post(
                f"{CENTRAL_REGISTRY_URL}/register",
                json=node_info,
                timeout=5
            )
            resp.raise_for_status()
            
            peers = resp.json().get("peers", [])
            for peer in peers:
                peer_url = f"http://{peer['ip']}:{peer['port']}/run"
                if peer_url not in self.peers:
                    self.peers.add(peer_url)
                    self.logger.info(f"Discovered central peer: {peer_url}")
            
            return True
        except Exception as e:
            self.logger.error(f"Central registration failed: {e}")
            return False

    def sync_with_central(self) -> None:
        """Periodically sync with central registry"""
        while True:
            try:
                if not self.register_with_central():
                    self.logger.warning("Central registry sync failed, retrying...")
                time.sleep(HEARTBEAT_INTERVAL)
            except Exception as e:
                self.logger.error(f"Sync error: {e}")
                time.sleep(HEARTBEAT_INTERVAL)

    def start(self) -> None:
        """Start all discovery services"""
        # Start LAN registration and discovery
        if self.register_service():
            self.discover_peers()
        
        # Start central registry integration
        if self.register_with_central():
            threading.Thread(target=self.sync_with_central, daemon=True).start()

        # Keep main thread alive
        try:
            while True:
                self.logger.info(f"Active peers: {len(self.peers)}")
                time.sleep(HEARTBEAT_INTERVAL)
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            if self.zeroconf:
                self.zeroconf.close()

if __name__ == "__main__":
    discovery = PeerDiscovery()
    discovery.start()