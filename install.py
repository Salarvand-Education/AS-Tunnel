import os
import sys
import subprocess
import signal
import socket
import termcolor
import requests
import yaml
from tqdm import tqdm

# مسیرهای فایل‌های پیکربندی
CONFIG_DIR = "/etc/traefik/"
CONFIG_FILE = os.path.join(CONFIG_DIR, "traefik.yml")
DYNAMIC_FILE = os.path.join(CONFIG_DIR, "dynamic.yml")
SERVICE_FILE = "/etc/systemd/system/traefik-tunnel.service"

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

def signal_handler(sig, frame):
    print(termcolor.colored("\nOperation cancelled by the user.", "red"))
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def check_requirements():
    try:
        subprocess.run(["which", "traefik"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        print(termcolor.colored("Traefik is not installed. Installing Traefik...", "yellow"))
        run_command(["curl", "-L", "https://github.com/traefik/traefik/releases/download/v3.1.0/traefik_v3.1.0_linux_amd64.tar.gz", "-o", "traefik.tar.gz"])
        run_command(["tar", "-xzf", "traefik.tar.gz"])
        run_command(["sudo", "mv", "traefik", "/usr/local/bin/"])
        os.remove("traefik.tar.gz")

def check_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        result = sock.connect_ex(('localhost', int(port)))
        return result != 0

def load_existing_config():
    traefik_config = {}
    dynamic_config = {"tcp": {"routers": {}, "services": {}}}
    
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            traefik_config = yaml.safe_load(f) or {}
    
    if os.path.exists(DYNAMIC_FILE):
        with open(DYNAMIC_FILE, 'r') as f:
            dynamic_config = yaml.safe_load(f) or {"tcp": {"routers": {}, "services": {}}}
    
    return traefik_config, dynamic_config

def merge_configs(existing_config, new_ports, ip_backend=None):
    # تنظیمات پایه اگر فایل خالی باشد
    if not existing_config:
        existing_config = {
            "entryPoints": {},
            "providers": {
                "file": {
                    "filename": "/etc/traefik/dynamic.yml"
                }
            },
            "api": {
                "dashboard": True,
                "insecure": True
            }
        }
    
    # اضافه کردن پورت‌های جدید
    for port in new_ports:
        entry_point_name = f"port_{port}"
        if "entryPoints" not in existing_config:
            existing_config["entryPoints"] = {}
        existing_config["entryPoints"][entry_point_name] = {
            "address": f":{port}"
        }
    
    return existing_config

def create_dynamic_config(ip_backend, new_ports, existing_config=None):
    if existing_config is None:
        existing_config = {"tcp": {"routers": {}, "services": {}}}
    
    # اضافه کردن کانفیگ‌های جدید
    for port in new_ports:
        router_name = f"tcp_router_{port}"
        service_name = f"tcp_service_{port}"
        
        existing_config["tcp"]["routers"][router_name] = {
            "entryPoints": [f"port_{port}"],
            "service": service_name,
            "rule": "HostSNI(`*`)"
        }
        
        existing_config["tcp"]["services"][service_name] = {
            "loadBalancer": {
                "servers": [
                    {"address": f"{ip_backend}:{port}"}
                ]
            }
        }
    
    return existing_config

def save_yaml_file(config, filename):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, indent=2, allow_unicode=True)

def install_tunnel():
    check_requirements()
    
    while True:
        print("\nSelect IP version:")
        print("1 - IPv6")
        print("2 - IPv4")
        version_choice = input("Enter your choice (1/2): ").strip()
        
        if version_choice in ['1', '2']:
            version = '6' if version_choice == '1' else '4'
            break
        print(termcolor.colored("Invalid choice. Please enter '1' or '2'.", "red"))

    ip_backend = input(f"\nEnter IPv{version} address of the backend server: ").strip()
    ports_input = input("\nEnter the ports to tunnel (comma-separated): ").strip()
    new_ports = [port.strip() for port in ports_input.split(',') if port.strip()]

    # Validate ports
    for port in new_ports:
        try:
            port_num = int(port)
            if not 1 <= port_num <= 65535:
                raise ValueError()
            if not check_port_available(port_num):
                print(termcolor.colored(f"Port {port} is already in use. Please choose another port.", "red"))
                return
        except ValueError:
            print(termcolor.colored(f"Invalid port number: {port}", "red"))
            return

    # Load existing configs
    existing_traefik, existing_dynamic = load_existing_config()

    # Merge configurations
    updated_traefik = merge_configs(existing_traefik, new_ports)
    updated_dynamic = create_dynamic_config(ip_backend, new_ports, existing_dynamic)

    # Save configurations
    save_yaml_file(updated_traefik, CONFIG_FILE)
    save_yaml_file(updated_dynamic, DYNAMIC_FILE)

    # Create service file if it doesn't exist
    if not os.path.exists(SERVICE_FILE):
        service_content = """[Unit]
Description=Traefik Tunnel Service
After=network.target

[Service]
ExecStart=/usr/local/bin/traefik --configFile=/etc/traefik/traefik.yml
Restart=always
User=root

[Install]
WantedBy=multi-user.target"""
        
        with open(SERVICE_FILE, "w") as f:
            f.write(service_content)

    run_command(["sudo", "systemctl", "daemon-reload"])
    run_command(["sudo", "systemctl", "enable", "traefik-tunnel.service"])
    run_command(["sudo", "systemctl", "restart", "traefik-tunnel.service"])

    print(termcolor.colored("\nTunnel configuration has been updated and service restarted.", "green"))

def delete_tunnel():
    if not os.path.exists(CONFIG_FILE) or not os.path.exists(DYNAMIC_FILE):
        print(termcolor.colored("No tunnel configuration found.", "red"))
        return

    print(termcolor.colored("\nCurrent tunnel configuration:", "yellow"))
    list_tunnels()
    
    ports_input = input("\nEnter the ports to delete (comma-separated): ").strip()
    ports_to_delete = [port.strip() for port in ports_input.split(',') if port.strip()]

    traefik_config, dynamic_config = load_existing_config()

    # Remove ports from traefik.yml
    if "entryPoints" in traefik_config:
        for port in ports_to_delete:
            entry_point = f"port_{port}"
            if entry_point in traefik_config["entryPoints"]:
                del traefik_config["entryPoints"][entry_point]

    # Remove configurations from dynamic.yml
    for port in ports_to_delete:
        router_name = f"tcp_router_{port}"
        service_name = f"tcp_service_{port}"
        
        if router_name in dynamic_config["tcp"]["routers"]:
            del dynamic_config["tcp"]["routers"][router_name]
        if service_name in dynamic_config["tcp"]["services"]:
            del dynamic_config["tcp"]["services"][service_name]

    # Save updated configurations
    save_yaml_file(traefik_config, CONFIG_FILE)
    save_yaml_file(dynamic_config, DYNAMIC_FILE)

    # Restart service
    run_command(["sudo", "systemctl", "restart", "traefik-tunnel.service"])
    print(termcolor.colored("\nSelected tunnels have been deleted and service restarted.", "green"))

def uninstall_tunnel():
    try:
        run_command(["sudo", "systemctl", "stop", "traefik-tunnel.service"])
        run_command(["sudo", "systemctl", "disable", "traefik-tunnel.service"])
        
        files_to_remove = [SERVICE_FILE, CONFIG_FILE, DYNAMIC_FILE]
        for file in files_to_remove:
            if os.path.exists(file):
                os.remove(file)
        
        run_command(["sudo", "systemctl", "daemon-reload"])
        print(termcolor.colored("\nTunnel service and configurations have been completely removed.", "green"))
    except Exception as e:
        print(termcolor.colored(f"\nError during uninstallation: {e}", "red"))

def list_tunnels():
    if not os.path.exists(CONFIG_FILE) or not os.path.exists(DYNAMIC_FILE):
        print(termcolor.colored("No tunnel configuration found.", "red"))
        return

    try:
        with open(CONFIG_FILE) as f:
            traefik_config = yaml.safe_load(f)
        with open(DYNAMIC_FILE) as f:
            dynamic_config = yaml.safe_load(f)

        print(termcolor.colored("\nConfigured Tunnels:", "green"))
        if traefik_config and "entryPoints" in traefik_config:
            for entry_point, config in traefik_config["entryPoints"].items():
                if entry_point.startswith("port_"):
                    port = config["address"].strip(":")
                    print(f"\nPort: {port}")
                    
                    # Find corresponding router and service
                    router_name = f"tcp_router_{port}"
                    service_name = f"tcp_service_{port}"
                    
                    if dynamic_config and "tcp" in dynamic_config:
                        if router_name in dynamic_config["tcp"]["routers"]:
                            if service_name in dynamic_config["tcp"]["services"]:
                                service = dynamic_config["tcp"]["services"][service_name]
                                if "loadBalancer" in service and "servers" in service["loadBalancer"]:
                                    backend = service["loadBalancer"]["servers"][0]["address"]
                                    print(f"  Backend: {backend}")

    except Exception as e:
        print(termcolor.colored(f"\nError reading configuration: {e}", "red"))

def display_tunnel_status():
    try:
        response = requests.get("http://localhost:8080/api/rawdata")
        if response.status_code == 200:
            status = response.json()
            
            print(termcolor.colored("\nActive Tunnels Status:", "green"))
            
            if 'tcp' in status and 'routers' in status['tcp']:
                for router, details in status['tcp']['routers'].items():
                    print(f"\nRouter: {router}")
                    print(f"  Status: {'✓ Active' if details.get('status') == 'enabled' else '✗ Inactive'}")
                    print(f"  Service: {details.get('service', 'N/A')}")
                    
                    # Show backend details
                    service_name = details.get('service')
                    if service_name and 'tcp' in status and 'services' in status['tcp']:
                        service = status['tcp']['services'].get(service_name, {})
                        if 'loadBalancer' in service and 'servers' in service['loadBalancer']:
                            for server in service['loadBalancer']['servers']:
                                print(f"  Backend: {server.get('address', 'N/A')}")
            else:
                print(termcolor.colored("No active TCP tunnels found.", "yellow"))
                
        else:
            print(termcolor.colored("Failed to retrieve Traefik status. Please check if Traefik is running.", "red"))
    except requests.exceptions.RequestException as e:
        print(termcolor.colored(f"Error connecting to Traefik API: {e}", "red"))

if __name__ == "__main__":
    check_and_install_modules()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == "install":
            install_tunnel()
        elif command == "uninstall":
            uninstall_tunnel()
        elif command == "status":
            display_tunnel_status()
        elif command == "delete":
            delete_tunnel()
        elif command == "list":
            list_tunnels()
        else:
            print("Invalid command. Use: install, uninstall, status, delete, or list")
    else:
        print("No command provided. Use: install, uninstall, status, delete, or list")
