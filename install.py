#!/usr/bin/env python3

import os
import sys
import subprocess
import signal
import socket
import termcolor
import requests
from tqdm import tqdm

# Constants
CONFIG_DIR = "/etc/traefik/"
CONFIG_FILE = os.path.join(CONFIG_DIR, "traefik.yml")
DYNAMIC_FILE = os.path.join(CONFIG_DIR, "dynamic.yml")
SERVICE_FILE = "/etc/systemd/system/traefik-tunnel.service"

# Function to run shell commands
def run_command(command):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    process.communicate()
    return process.returncode

# Function to handle Ctrl+C
def signal_handler(sig, frame):
    print(termcolor.colored("\nOperation cancelled by the user.", "red"))
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# Function to check if Traefik is installed
def check_requirements():
    try:
        subprocess.run(["which", "traefik"], check=True)
    except subprocess.CalledProcessError:
        print(termcolor.colored("Traefik is not installed. Installing Traefik...", "yellow"))
        run_command(["curl", "-L", "https://github.com/traefik/traefik/releases/download/v3.1.0/traefik_v3.1.0_linux_amd64.tar.gz", "-o", "traefik.tar.gz"])
        run_command(["tar", "-xvzf", "traefik.tar.gz"])
        run_command(["sudo", "mv", "traefik", "/usr/local/bin/"])
        os.remove("traefik.tar.gz")

# Function to check if a port is available
def check_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        result = sock.connect_ex(('localhost', port))
        return result != 0

# Function to create Traefik config files
def create_config_files(ip_backend, ports_list):
    traefik_config = "entryPoints:\n"
    for port in ports_list:
        traefik_config += f"  port_{port}:\n    address: ':{port}'\n"
    traefik_config += f"providers:\n  file:\n    filename: '{DYNAMIC_FILE}'\napi:\n  dashboard: true\n  insecure: true\n"

    dynamic_config = "tcp:\n  routers:\n"
    for port in ports_list:
        dynamic_config += f"    tcp_router_{port}:\n      entryPoints:\n        - port_{port}\n      service: tcp_service_{port}\n      rule: 'HostSNI(`*`)'\n"
    dynamic_config += "  services:\n"
    for port in ports_list:
        dynamic_config += f"    tcp_service_{port}:\n      loadBalancer:\n        servers:\n          - address: '{ip_backend}:{port}'\n"

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as traefik_file:
        traefik_file.write(traefik_config)
    with open(DYNAMIC_FILE, "w") as dynamic_file:
        dynamic_file.write(dynamic_config)

# Function to install the tunnel
def install_tunnel():
    check_requirements()
    
    while True:
        print("Select IP version:")
        print("1 - IPv6")
        print("2 - IPv4")
        version_choice = input("Enter your choice: ")
        
        if version_choice == "1":
            version = '6'
            break
        elif version_choice == "2":
            version = '4'
            break
        else:
            print(termcolor.colored("Invalid choice. Please enter '1' or '2'.", "red"))

    ip_backend = input(f"Enter IPv{version} address of the backend server: ")
    ports = input("Enter the ports to tunnel (comma-separated): ")
    ports_list = ports.split(',')

    for port in ports_list:
        if not check_port_available(int(port)):
            print(termcolor.colored(f"Port {port} is already in use. Please choose another port.", "red"))
            return

    create_config_files(ip_backend, ports_list)

    service_file_content = f"""
[Unit]
Description=Traefik Tunnel Service
After=network.target

[Service]
ExecStart=/usr/local/bin/traefik --configFile={CONFIG_FILE}
Restart=always
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    with open(SERVICE_FILE, "w") as service_file:
        service_file.write(service_file_content)

    run_command(["sudo", "systemctl", "daemon-reload"])
    run_command(["sudo", "systemctl", "enable", "traefik-tunnel.service"])
    run_command(["sudo", "systemctl", "start", "traefik-tunnel.service"])

    print(termcolor.colored("Tunnel is being established and the service is running in the background...", "green"))

# Function to uninstall the tunnel
def uninstall_tunnel():
    try:
        run_command(["sudo", "systemctl", "stop", "traefik-tunnel.service"])
        run_command(["sudo", "systemctl", "disable", "traefik-tunnel.service"])
        if os.path.exists(SERVICE_FILE):
            os.remove(SERVICE_FILE)
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        if os.path.exists(DYNAMIC_FILE):
            os.remove(DYNAMIC_FILE)
        run_command(["sudo", "systemctl", "daemon-reload"])
        print(termcolor.colored("Tunnel has been successfully removed.", "green"))
    except Exception as e:
        print(termcolor.colored(f"An error occurred while removing the tunnel: {e}", "red"))

# Function to start the tunnel service
def start_tunnel():
    run_command(["sudo", "systemctl", "start", "traefik-tunnel.service"])
    print(termcolor.colored("Tunnel service started.", "green"))

# Function to stop the tunnel service
def stop_tunnel():
    run_command(["sudo", "systemctl", "stop", "traefik-tunnel.service"])
    print(termcolor.colored("Tunnel service stopped.", "green"))

# Function to restart the tunnel service
def restart_tunnel():
    run_command(["sudo", "systemctl", "restart", "traefik-tunnel.service"])
    print(termcolor.colored("Tunnel service restarted.", "green"))

# Function to display tunnel status
def display_tunnel_status():
    try:
        response = requests.get("http://localhost:8080/api/rawdata")
        if response.status_code == 200:
            status = response.json()
            routers = status.get('tcp', {}).get('routers', {})
            services = status.get('tcp', {}).get('services', {})
            
            print(termcolor.colored("Routers:", "yellow"))
            for router, details in routers.items():
                print(f"  - {router}: {details}")

            print(termcolor.colored("Services:", "yellow"))
            for service, details in services.items():
                print(f"  - {service}: {details}")
            print(termcolor.colored("Tunnel is up and running.", "green"))
        else:
            print(termcolor.colored("Failed to retrieve Traefik status. Please check if Traefik is running.", "red"))
    except requests.exceptions.RequestException as e:
        print(termcolor.colored(f"Error connecting to Traefik API: {e}", "red"))

# Function to add a new tunnel
def add_tunnel():
    ip_backend = input("Enter IP address of the backend server: ")
    ports = input("Enter the ports to tunnel (comma-separated): ")
    ports_list = ports.split(',')

    for port in ports_list:
        if not check_port_available(int(port)):
            print(termcolor.colored(f"Port {port} is already in use. Please choose another port.", "red"))
            return

    create_config_files(ip_backend, ports_list)
    restart_tunnel()
    print(termcolor.colored("New tunnel added and service restarted.", "green"))

# Function to delete a tunnel
def delete_tunnel():
    port = input("Enter the port to delete: ")
    if not os.path.exists(DYNAMIC_FILE):
        print(termcolor.colored("No tunnels configured.", "red"))
        return

    with open(DYNAMIC_FILE, "r") as dynamic_file:
        lines = dynamic_file.readlines()

    with open(DYNAMIC_FILE, "w") as dynamic_file:
        for line in lines:
            if f"port_{port}" not in line and f"tcp_router_{port}" not in line and f"tcp_service_{port}" not in line:
                dynamic_file.write(line)

    restart_tunnel()
    print(termcolor.colored(f"Tunnel for port {port} has been deleted.", "green"))

# Function to view all tunnels
def view_tunnels():
    if not os.path.exists(DYNAMIC_FILE):
        print(termcolor.colored("No tunnels configured.", "red"))
        return

    with open(DYNAMIC_FILE, "r") as dynamic_file:
        lines = dynamic_file.readlines()

    tunnels = []
    for line in lines:
        if "address: '" in line:
            # Extract IP and port from the line
            ip_port = line.split("address: '")[1].split("'")[0]
            tunnels.append(ip_port)

    if not tunnels:
        print(termcolor.colored("No tunnels configured.", "red"))
        return

    print(termcolor.colored("Configured Tunnels:", "yellow"))
    for i, tunnel in enumerate(tunnels, start=1):
        print(f"{i}: {tunnel}")

# Main function
def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "install":
            install_tunnel()
        elif sys.argv[1] == "uninstall":
            uninstall_tunnel()
        elif sys.argv[1] == "start":
            start_tunnel()
        elif sys.argv[1] == "stop":
            stop_tunnel()
        elif sys.argv[1] == "restart":
            restart_tunnel()
        elif sys.argv[1] == "status":
            display_tunnel_status()
        elif sys.argv[1] == "add":
            add_tunnel()
        elif sys.argv[1] == "delete":
            delete_tunnel()
        elif sys.argv[1] == "view":
            view_tunnels()
        else:
            print("Invalid argument. Use 'install', 'uninstall', 'start', 'stop', 'restart', 'status', 'add', 'delete', or 'view'.")
    else:
        print("Usage: python3 install.py [install|uninstall|start|stop|restart|status|add|delete|view]")

if __name__ == "__main__":
    main()
