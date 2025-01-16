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

def run_command(command):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        print(termcolor.colored(f"Error: {stderr}", "red"))
    return process.returncode

def check_and_install_modules():
    modules = ["tqdm", "termcolor", "requests", "pyyaml"]
    try:
        import pkg_resources
        installed = {pkg.key for pkg in pkg_resources.working_set}
        for module in modules:
            if module not in installed:
                run_command([sys.executable, "-m", "pip", "install", module])
    except Exception:
        run_command(["sudo", "apt", "update"])
        run_command(["sudo", "apt", "install", "-y", "python3-pip"])
        for module in modules:
            run_command([sys.executable, "-m", "pip", "install", module])

class TunnelManager:
    def __init__(self, api_port):
        self.api_port = api_port
        self.running = False
        self.monitor_thread = None
        self.last_error = None
        self.tunnels = {}
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print(termcolor.colored("\nReceived shutdown signal. Cleaning up...", "yellow"))
        self.stop_monitoring()
        sys.exit(0)

    def _check_requirements(self):
        try:
            subprocess.run(["which", "traefik"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            print(termcolor.colored("Traefik is not installed. Installing Traefik...", "yellow"))
            run_command(["curl", "-L", "https://github.com/traefik/traefik/releases/download/v3.1.0/traefik_v3.1.0_linux_amd64.tar.gz", "-o", "traefik.tar.gz"])
            run_command(["tar", "-xzf", "traefik.tar.gz"])
            run_command(["sudo", "mv", "traefik", "/usr/local/bin/"])
            os.remove("traefik.tar.gz")

    def start_monitoring(self):
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_tunnels)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        print(termcolor.colored("Tunnel monitoring started", "green"))

    def stop_monitoring(self):
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        print(termcolor.colored("Tunnel monitoring stopped", "yellow"))

    def _monitor_tunnels(self):
        while self.running:
            try:
                self._check_service_health()
                time.sleep(KEEPALIVE_INTERVAL)
            except Exception as e:
                self.last_error = str(e)
                print(termcolor.colored(f"Error detected: {self.last_error}", "red"))
                self._attempt_recovery()

    def _check_service_health(self):
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "traefik-tunnel.service"],
                capture_output=True,
                text=True
            )
            if result.stdout.strip() != "active":
                print(termcolor.colored("Service is not running. Starting service...", "yellow"))
                subprocess.run(["sudo", "systemctl", "start", "traefik-tunnel.service"])
                time.sleep(5)
            
            api_url = f"http://localhost:{self.api_port}/api/rawdata"
            response = requests.get(api_url, timeout=5)
            if response.status_code != 200:
                raise Exception(f"API returned status {response.status_code}")

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to connect to Traefik API: {str(e)}")
        except Exception as e:
            raise Exception(f"Health check failed: {str(e)}")

    def _attempt_recovery(self):
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

    def install_tunnel(self, ip_version, ip_backend, ports):
        try:
            self._validate_inputs(ip_version, ip_backend, ports)
            self._check_requirements()
            self._create_configs(ip_backend, ports)
            self._setup_service()
            self.start_monitoring()
            return True
        except Exception as e:
            print(termcolor.colored(f"Installation failed: {str(e)}", "red"))
            return False

    def delete_tunnel(self, ports_to_delete):
        try:
            traefik_config = self._load_config(CONFIG_FILE)
            dynamic_config = self._load_config(DYNAMIC_FILE)

            if not traefik_config or not dynamic_config:
                print(termcolor.colored("No tunnel configuration found.", "red"))
                return False

            for port in ports_to_delete:
                entry_point = f"port_{port}"
                if "entryPoints" in traefik_config and entry_point in traefik_config["entryPoints"]:
                    del traefik_config["entryPoints"][entry_point]

                router_name = f"tcp_router_{port}"
                service_name = f"tcp_service_{port}"

                if router_name in dynamic_config["tcp"]["routers"]:
                    del dynamic_config["tcp"]["routers"][router_name]
                if service_name in dynamic_config["tcp"]["services"]:
                    del dynamic_config["tcp"]["services"][service_name]

            self._save_config(CONFIG_FILE, traefik_config)
            self._save_config(DYNAMIC_FILE, dynamic_config)

            subprocess.run(["sudo", "systemctl", "restart", "traefik-tunnel.service"], check=True)
            print(termcolor.colored("\nSelected tunnels have been deleted successfully.", "green"))
            return True

        except Exception as e:
            print(termcolor.colored(f"Error deleting tunnels: {str(e)}", "red"))
            return False

    def uninstall(self):
        try:
            print(termcolor.colored("Stopping Traefik service...", "yellow"))
            subprocess.run(["sudo", "systemctl", "stop", "traefik-tunnel.service"], check=True)
            subprocess.run(["sudo", "systemctl", "disable", "traefik-tunnel.service"], check=True)

            files_to_remove = [
                SERVICE_FILE,
                CONFIG_FILE,
                DYNAMIC_FILE
            ]

            for file in files_to_remove:
                if os.path.exists(file):
                    os.remove(file)
                    print(termcolor.colored(f"Removed {file}", "yellow"))

            if os.path.exists(CONFIG_DIR) and not os.listdir(CONFIG_DIR):
                os.rmdir(CONFIG_DIR)

            if input("Remove Traefik binary? (y/N): ").lower() == 'y':
                if os.path.exists("/usr/local/bin/traefik"):
                    subprocess.run(["sudo", "rm", "/usr/local/bin/traefik"], check=True)
                    print(termcolor.colored("Removed Traefik binary", "yellow"))

            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            print(termcolor.colored("\nTraefik Tunnel Manager has been completely uninstalled.", "green"))
            return True

        except Exception as e:
            print(termcolor.colored(f"Error during uninstallation: {str(e)}", "red"))
            return False

    def _validate_inputs(self, ip_version, ip_backend, ports):
        if ip_version not in ['4', '6']:
            raise ValueError("Invalid IP version")
            
        try:
            socket.inet_pton(socket.AF_INET if ip_version == '4' else socket.AF_INET6, ip_backend)
        except socket.error:
            raise ValueError(f"Invalid IPv{ip_version} address format")

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
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('localhost', port))
                return True
            except socket.error:
                return False

    def _get_default_traefik_config(self):
        return {
            "entryPoints": {
                "api": {
                    "address": f":{self.api_port}"
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

    def _create_configs(self, ip_backend, ports):
        traefik_config = self._load_config(CONFIG_FILE) or self._get_default_traefik_config()
        dynamic_config = self._load_config(DYNAMIC_FILE) or {"tcp": {"routers": {}, "services": {}}}

        self._update_traefik_config(traefik_config, ports)
        self._update_dynamic_config(dynamic_config, ip_backend, ports)

        self._save_config(CONFIG_FILE, traefik_config)
        self._save_config(DYNAMIC_FILE, dynamic_config)

    def _update_traefik_config(self, config, ports):
        for port in ports:
            entry_point_name = f"port_{port}"
            if "entryPoints" not in config:
                config["entryPoints"] = {}
            config["entryPoints"][entry_point_name] = {
                "address": f":{port}"
            }

    def _update_dynamic_config(self, config, ip_backend, ports):
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
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            print(termcolor.colored(f"Error loading config {filename}: {str(e)}", "red"))
        return None

    def _save_config(self, filename, config):
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
        except Exception as e:
            raise Exception(f"Failed to save config {filename}: {str(e)}")

    def get_status(self):
        try:
            api_url = f"http://localhost:{self.api_port}/api/rawdata"
            response = requests.get(api_url, timeout=5)
            if response.status_code == 200:
                return self._parse_status(response.json())
            return {"error": f"API returned status {response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Connection error: {str(e)}"}

    def _parse_status(self, status_data):
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
                     def _get_backend_address(self, service_name, status_data):
        try:
            service = status_data['tcp']['services'][service_name]
            return service['loadBalancer']['servers'][0]['address']
        except (KeyError, IndexError):
            return "unknown"

def main():
    # Get API port from command line arguments
    api_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081

    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        manager = TunnelManager(api_port)
        
        if command == "install":
            version = input("Enter IP version (4/6): ").strip()
            ip = input("Enter backend IP: ").strip()
            ports = input("Enter ports (comma-separated): ").strip().split(',')
            manager.install_tunnel(version, ip, ports)
            
        elif command == "delete":
            ports_input = input("\nEnter the ports to delete (comma-separated): ").strip()
            ports_to_delete = [port.strip() for port in ports_input.split(',') if port.strip()]
            manager.delete_tunnel(ports_to_delete)
            
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
                
        elif command == "uninstall":
            if input("\nAre you sure you want to uninstall? This will remove all configurations. (y/N): ").lower() == 'y':
                manager.uninstall()
        else:
            print(termcolor.colored(f"Unknown command: {command}", "red"))
            print("Available commands: install, delete, status, monitor, uninstall")
    else:
        print(termcolor.colored("No command provided", "red"))
        print("Available commands: install, delete, status, monitor, uninstall")

if __name__ == "__main__":
    check_and_install_modules()
    main()                                    
