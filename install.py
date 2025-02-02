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
        self.server_ip = self._get_server_ip()
        self._setup_signal_handlers()

    def _get_server_ip(self):
        try:
            cmd = "curl -s http://ipv4.icanhazip.com"
            public_ip = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            if public_ip:
                return public_ip
        except:
            try:
                cmd = "hostname -I | cut -d' ' -f1"
                local_ip = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
                return local_ip
            except:
                return '0.0.0.0'

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
            run_command(["sudo", "chmod", "+x", "/usr/local/bin/traefik"])
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
            print(termcolor.colored("Checking service health...", "yellow"))
            
            # First, check service status
            result = subprocess.run(["systemctl", "is-active", "traefik-tunnel.service"],
                                 capture_output=True, text=True)
            
            if result.stdout.strip() != "active":
                print(termcolor.colored("Service is not active. Checking logs...", "yellow"))
                logs = subprocess.run(["journalctl", "-u", "traefik-tunnel.service", "-n", "50"],
                                    capture_output=True, text=True)
                print(logs.stdout)
                
                print(termcolor.colored("Attempting to restart service...", "yellow"))
                subprocess.run(["sudo", "systemctl", "restart", "traefik-tunnel.service"])
                time.sleep(10)
                
            # Try to connect to API
            print(termcolor.colored(f"Checking API connection on port {self.api_port}...", "yellow"))
            api_urls = [
                f"http://127.0.0.1:{self.api_port}/api/rawdata",
                f"http://localhost:{self.api_port}/api/rawdata",
                f"http://0.0.0.0:{self.api_port}/api/rawdata"
            ]
            
            connected = False
            for url in api_urls:
                try:
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        print(termcolor.colored(f"Successfully connected to API at {url}", "green"))
                        connected = True
                        break
                except:
                    continue
                    
            if not connected:
                raise Exception("Could not connect to Traefik API")

        except Exception as e:
            print(termcolor.colored(f"Service health check failed: {str(e)}", "red"))
            raise

    def _get_default_traefik_config(self):
        return {
            "entryPoints": {
                "traefik": {
                    "address": f"0.0.0.0:{self.api_port}"
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
                "level": "DEBUG",
                "format": "common"
            },
            "accessLog": {}
        }

    def _setup_service(self):
        service_content = f"""[Unit]
Description=Traefik Tunnel Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/traefik \\
    --configfile=/etc/traefik/traefik.yml \\
    --api.dashboard=true \\
    --api.insecure=true \\
    --entrypoints.traefik.address=0.0.0.0:{self.api_port} \\
    --log.level=DEBUG
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
        
        # Stop service if running
        try:
            subprocess.run(["sudo", "systemctl", "stop", "traefik-tunnel.service"], check=True)
            time.sleep(2)
        except:
            pass
            
        # Start service
        print(termcolor.colored("Starting Traefik service...", "yellow"))
        subprocess.run(["sudo", "systemctl", "start", "traefik-tunnel.service"], check=True)
        time.sleep(5)
        
        # Check service status
        status = subprocess.run(["sudo", "systemctl", "status", "traefik-tunnel.service"], 
                              capture_output=True, text=True)
        print(status.stdout)

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
        """Install and configure a new tunnel."""
        try:
            self._validate_inputs(ip_version, ip_backend, ports)
            self._check_requirements()
            self._create_configs(ip_backend, ports)
            self._setup_service()
            self.start_monitoring()
            print(termcolor.colored("Tunnel installed successfully!", "green"))
            return True
        except Exception as e:
            print(termcolor.colored(f"Installation failed: {str(e)}", "red"))
            return False

    def delete_tunnel(self, ports_to_delete):
        """Delete one or more tunnels by their ports."""
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
        """Uninstall the Traefik Tunnel Manager and remove all configurations."""
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
        """Validate user inputs for IP version, backend IP, and ports."""
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
        """Check if a port is available for binding."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('0.0.0.0', port))
                return True
            except socket.error:
                return False

    def _create_configs(self, ip_backend, ports):
        """Create Traefik configuration files."""
        traefik_config = self._load_config(CONFIG_FILE) or self._get_default_traefik_config()
        dynamic_config = self._load_config(DYNAMIC_FILE) or {"tcp": {"routers": {}, "services": {}}}

        self._update_traefik_config(traefik_config, ports)
        self._update_dynamic_config(dynamic_config, ip_backend, ports)

        self._save_config(CONFIG_FILE, traefik_config)
        self._save_config(DYNAMIC_FILE, dynamic_config)

    def _update_traefik_config(self, config, ports):
        """Update Traefik configuration with new ports."""
        for port in ports:
            entry_point_name = f"port_{port}"
            if "entryPoints" not in config:
                config["entryPoints"] = {}
            config["entryPoints"][entry_point_name] = {
                "address": f"0.0.0.0:{port}"
            }

    def _update_dynamic_config(self, config, ip_backend, ports):
        """Update dynamic configuration with backend IP and ports."""
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

    def _load_config(self, filename):
        """Load a YAML configuration file."""
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            print(termcolor.colored(f"Error loading config {filename}: {str(e)}", "red"))
        return None

    def _save_config(self, filename, config):
        """Save a YAML configuration file."""
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
        except Exception as e:
            raise Exception(f"Failed to save config {filename}: {str(e)}")

    def get_status(self):
        """Get detailed status of all configured tunnels."""
        try:
            # First check if service is running
            service_status = subprocess.run(
                ["systemctl", "is-active", "traefik-tunnel.service"],
                capture_output=True,
                text=True
            ).stdout.strip()

            if service_status != "active":
                return {
                    "status": "error",
                    "message": "Traefik service is not running",
                    "active_tunnels": []
                }

            # Try to get status from config files first
            tunnels = self._get_tunnels_from_config()
            
            # Then try to get additional status from API
            api_status = self._get_api_status()
            
            # Merge config and API status
            for tunnel in tunnels:
                api_tunnel = next(
                    (t for t in api_status.get("active_tunnels", []) 
                     if t["port"] == tunnel["port"]), 
                    None
                )
                if api_tunnel:
                    tunnel.update(api_tunnel)
                else:
                    tunnel["status"] = "configured but not active"

            return {
                "status": "ok",
                "server_ip": self.server_ip,
                "active_tunnels": tunnels
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "active_tunnels": []
            }

    def _get_tunnels_from_config(self):
        """Extract tunnel information from configuration files."""
        tunnels = []
        try:
            # Load configs
            traefik_config = self._load_config(CONFIG_FILE) or {}
            dynamic_config = self._load_config(DYNAMIC_FILE) or {}

            # Get entrypoints (ports)
            entrypoints = traefik_config.get("entryPoints", {})
            
            # Get services (backend destinations)
            tcp_services = dynamic_config.get("tcp", {}).get("services", {})
            
            # Match ports with their backend services
            for entry_name, entry_data in entrypoints.items():
                if entry_name.startswith("port_"):
                    port = entry_name.replace("port_", "")
                    service_name = f"tcp_service_{port}"
                    
                    tunnel = {
                        "port": port,
                        "local_address": entry_data.get("address", "unknown"),
                        "backend": "unknown",
                        "status": "unknown"
                    }
                    
                    # Get backend information
                    if service_name in tcp_services:
                        servers = tcp_services[service_name].get("loadBalancer", {}).get("servers", [])
                        if servers:
                            tunnel["backend"] = servers[0].get("address", "unknown")
                    
                    tunnels.append(tunnel)
                    
            return tunnels
        except Exception as e:
            print(termcolor.colored(f"Error reading config: {str(e)}", "red"))
            return []

    def _get_api_status(self):
        """Get status information from Traefik API."""
        api_urls = [
            f"http://127.0.0.1:{self.api_port}/api/tcp/routers",
            f"http://localhost:{self.api_port}/api/tcp/routers",
            f"http://0.0.0.0:{self.api_port}/api/tcp/routers"
        ]
        
        for url in api_urls:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    active_tunnels = []
                    routers_data = response.json()
                    
                    for router in routers_data:
                        if "tcp" in router.get("service", ""):
                            port = router["service"].split("_")[-1]
                            active_tunnels.append({
                                "port": port,
                                "status": "active" if router.get("status") == "enabled" else "inactive",
                                "rule": router.get("rule", "unknown"),
                                "service": router.get("service")
                            })
                    
                    return {"active_tunnels": active_tunnels}
            except:
                continue
        
        return {"active_tunnels": []}

    def _format_status_output(self, status):
        """Format status information for display."""
        output = []
        output.append(f"\nServer IP: {status.get('server_ip', 'unknown')}")
        output.append("\nActive Tunnels:")
        
        tunnels = status.get("active_tunnels", [])
        if not tunnels:
            output.append("  No active tunnels found")
        else:
            for tunnel in tunnels:
                output.append(f"\n  Port: {tunnel.get('port', 'unknown')}")
                output.append(f"  Status: {tunnel.get('status', 'unknown')}")
                output.append(f"  Backend: {tunnel.get('backend', 'unknown')}")
                output.append(f"  Local Address: {tunnel.get('local_address', 'unknown')}")
                output.append("")
        
        return "\n".join(output)

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
            if status.get("status") == "error":
                print(termcolor.colored(f"\nError: {status.get('message', 'Unknown error')}", "red"))
            else:
                print(termcolor.colored(manager._format_status_output(status), "green"))
            
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
