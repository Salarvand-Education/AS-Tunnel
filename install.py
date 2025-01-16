import os
import sys
import subprocess
import signal
import socket
import time
import threading
from datetime import datetime
import termcolor
import requests
import yaml
from tqdm import tqdm

# Global Configuration
CONFIG_DIR = "/etc/traefik/"
CONFIG_FILE = os.path.join(CONFIG_DIR, "traefik.yml")
DYNAMIC_FILE = os.path.join(CONFIG_DIR, "dynamic.yml")
SERVICE_FILE = "/etc/systemd/system/traefik-tunnel.service"
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5
KEEPALIVE_INTERVAL = 30

class TunnelManager:
    def __init__(self):
        self.running = False
        self.monitor_thread = None
        self.last_error = None
        self.tunnels = {}
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup handlers for system signals"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle system signals gracefully"""
        print(termcolor.colored("\nReceived shutdown signal. Cleaning up...", "yellow"))
        self.stop_monitoring()
        sys.exit(0)

    def start_monitoring(self):
        """Start tunnel monitoring"""
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_tunnels)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        print(termcolor.colored("Tunnel monitoring started", "green"))

    def stop_monitoring(self):
        """Stop tunnel monitoring"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        print(termcolor.colored("Tunnel monitoring stopped", "yellow"))

    def _monitor_tunnels(self):
        """Continuously monitor tunnels and attempt recovery if needed"""
        while self.running:
            try:
                self._check_service_health()
                self._update_tunnel_status()
                time.sleep(KEEPALIVE_INTERVAL)
            except Exception as e:
                self.last_error = str(e)
                print(termcolor.colored(f"Error detected: {self.last_error}", "red"))
                self._attempt_recovery()

    def _check_service_health(self):
        """Check the health of the Traefik service"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "traefik-tunnel.service"],
                capture_output=True,
                text=True,
                check=True
            )
            if result.stdout.strip() != "active":
                raise Exception("Traefik service is not active")

            response = requests.get("http://localhost:8080/api/rawdata", timeout=5)
            if response.status_code != 200:
                raise Exception(f"API returned unexpected status: {response.status_code}")

        except subprocess.CalledProcessError:
            raise Exception("Failed to check service status")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to connect to Traefik API: {str(e)}")

    def _attempt_recovery(self):
        """Attempt to recover the service after failure"""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                print(termcolor.colored(f"Recovery attempt {attempt + 1}/{RETRY_ATTEMPTS}...", "yellow"))
                subprocess.run(["sudo", "systemctl", "restart", "traefik-tunnel.service"], check=True)
                time.sleep(RETRY_DELAY)
                self._check_service_health()
                print(termcolor.colored("Service recovered successfully", "green"))
                return
            except Exception as e:
                if attempt == RETRY_ATTEMPTS - 1:
                    print(termcolor.colored(f"Failed to recover service after {RETRY_ATTEMPTS} attempts", "red"))
                    self._log_error(str(e))

    def _log_error(self, error_message):
        """Log error messages with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_log = f"[{timestamp}] {error_message}\n"
        try:
            with open(os.path.join(CONFIG_DIR, "tunnel_errors.log"), "a") as f:
                f.write(error_log)
        except Exception:
            pass  # Fail silently if cannot write to log

    def install_tunnel(self, ip_version, ip_backend, ports):
        """Install new tunnel with recovery mechanism"""
        try:
            self._validate_inputs(ip_version, ip_backend, ports)
            self._create_configs(ip_version, ip_backend, ports)
            self._setup_service()
            self.start_monitoring()
            return True
        except Exception as e:
            print(termcolor.colored(f"Installation failed: {str(e)}", "red"))
            self._log_error(f"Installation error: {str(e)}")
            return False

    def _validate_inputs(self, ip_version, ip_backend, ports):
        """Validate input parameters"""
        if ip_version not in ['4', '6']:
            raise ValueError("Invalid IP version. Must be '4' or '6'")

        # Validate IP address format
        try:
            socket.inet_pton(socket.AF_INET if ip_version == '4' else socket.AF_INET6, ip_backend)
        except socket.error:
            raise ValueError(f"Invalid IPv{ip_version} address format")

        # Validate ports
        for port in ports:
            try:
                port_num = int(port)
                if not 1 <= port_num <= 65535:
                    raise ValueError(f"Port {port} out of valid range (1-65535)")
                if not self._check_port_available(port_num):
                    raise ValueError(f"Port {port} is already in use")
            except ValueError as e:
                raise ValueError(f"Invalid port number: {str(e)}")

    def _check_port_available(self, port):
        """Check if a port is available for use"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('localhost', port))
                return True
            except socket.error:
                return False

    def _create_configs(self, ip_version, ip_backend, ports):
        """Create Traefik configuration files"""
        # Load existing configurations or create new ones
        traefik_config = self._load_config(CONFIG_FILE) or self._get_default_traefik_config()
        dynamic_config = self._load_config(DYNAMIC_FILE) or {"tcp": {"routers": {}, "services": {}}}

        # Update configurations
        self._update_traefik_config(traefik_config, ports)
        self._update_dynamic_config(dynamic_config, ip_backend, ports)

        # Save configurations
        self._save_config(CONFIG_FILE, traefik_config)
        self._save_config(DYNAMIC_FILE, dynamic_config)

    def _get_default_traefik_config(self):
        """Get default Traefik configuration"""
        return {
            "entryPoints": {
                "dashboard": {
                    "address": ":8080"
                }
            },
            "api": {
                "dashboard": True,
                "insecure": True
            },
            "providers": {
                "file": {
                    "filename": DYNAMIC_FILE
                }
            },
            "log": {
                "level": "INFO"
            }
        }

    def _update_traefik_config(self, config, ports):
        """Update Traefik configuration with new ports"""
        for port in ports:
            entry_point_name = f"port_{port}"
            config["entryPoints"][entry_point_name] = {
                "address": f":{port}"
            }

    def _update_dynamic_config(self, config, ip_backend, ports):
        """Update dynamic configuration with new tunnels"""
        for port in ports:
            router_name = f"tcp_router_{port}"
            service_name = f"tcp_service_{port}"

            config["tcp"]["routers"][router_name] = {
                "entryPoints": [f"port_{port}"],
                "service": service_name,
                "rule": "HostSNI(`*`)"
            }

            config["tcp"]["services"][service_name] = {
                "loadBalancer": {
                    "servers": [{"address": f"{ip_backend}:{port}"}]
                }
            }

    def _setup_service(self):
        """Setup and configure the Traefik service"""
        service_content = """[Unit]
Description=Traefik Tunnel Service
After=network.target

[Service]
ExecStart=/usr/local/bin/traefik --configFile=/etc/traefik/traefik.yml
Restart=always
RestartSec=5
StartLimitInterval=0
User=root

[Install]
WantedBy=multi-user.target"""

        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SERVICE_FILE, "w") as f:
            f.write(service_content)

        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "traefik-tunnel.service"], check=True)
        subprocess.run(["sudo", "systemctl", "restart", "traefik-tunnel.service"], check=True)

    def _load_config(self, filename):
        """Load YAML configuration file"""
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            print(termcolor.colored(f"Error loading config {filename}: {str(e)}", "red"))
        return None

    def _save_config(self, filename, config):
        """Save YAML configuration file"""
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
        except Exception as e:
            raise Exception(f"Failed to save config {filename}: {str(e)}")

    def get_status(self):
        """Get current tunnel status"""
        try:
            response = requests.get("http://localhost:8080/api/rawdata", timeout=5)
            if response.status_code == 200:
                return self._parse_status(response.json())
            return {"error": f"API returned status {response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Connection error: {str(e)}"}

    def _parse_status(self, status_data):
        """Parse status data from Traefik API"""
        result = {
            "active_tunnels": [],
            "errors": []
        }

        if 'tcp' in status_data and 'routers' in status_data['tcp']:
            for router, details in status_data['tcp']['routers'].items():
                tunnel_info = {
                    "name": router,
                    "status": "active" if details.get('status') == 'enabled' else "inactive",
                    "service": details.get('service'),
                    "backend": self._get_backend_address(details.get('service'), status_data)
                }
                result["active_tunnels"].append(tunnel_info)

        return result

    def _get_backend_address(self, service_name, status_data):
        """Get backend address for a service"""
        try:
            service = status_data['tcp']['services'][service_name]
            return service['loadBalancer']['servers'][0]['address']
        except (KeyError, IndexError):
            return "unknown"

def main():
    """Main entry point"""
    manager = TunnelManager()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "install":
            version = input("Enter IP version (4/6): ").strip()
            ip = input("Enter backend IP: ").strip()
            ports = input("Enter ports (comma-separated): ").strip().split(',')
            manager.install_tunnel(version, ip, ports)
            
        elif command == "status":
            status = manager.get_status()
            print(termcolor.colored("\nTunnel Status:", "green"))
            print(yaml.dump(status, default_flow_style=False))
            
        elif command == "monitor":
            try:
                manager.start_monitoring()
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                manager.stop_monitoring()
        else:
            print(termcolor.colored(f"Unknown command: {command}", "red"))
            print("Available commands: install, status, monitor")
    else:
        print(termcolor.colored("No command provided", "red"))
        print("Available commands: install, status, monitor")

if __name__ == "__main__":
    main()
