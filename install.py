#!/usr/bin/env python3

import os
import subprocess
import sys
import socket
import yaml
import argparse

# Constants
CONFIG_DIR = "/etc/traefik/"
CONFIG_FILE = os.path.join(CONFIG_DIR, "traefik.yml")
DYNAMIC_FILE = os.path.join(CONFIG_DIR, "dynamic.yml")
SERVICE_FILE = "/etc/systemd/system/traefik-tunnel.service"
TUNNELS_FILE = os.path.join(CONFIG_DIR, "tunnels.conf")
DEFAULT_PORT = 7000  # Default port for Traefik

# Function to run shell commands
def run_command(command):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        print(f"Error: {stderr}")
    return process.returncode

# Function to install Traefik
def install_traefik():
    print("Installing Traefik...")
    if not os.path.exists("/usr/local/bin/traefik"):
        run_command(["curl", "-L", "https://github.com/traefik/traefik/releases/download/v3.1.0/traefik_v3.1.0_linux_amd64.tar.gz", "-o", "traefik.tar.gz"])
        run_command(["tar", "-xvzf", "traefik.tar.gz"])
        run_command(["sudo", "mv", "traefik", "/usr/local/bin/"])
        os.remove("traefik.tar.gz")
    else:
        print("Traefik is already installed.")

# Function to create config files
def create_config_files():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

    # Create traefik.yml
    traefik_config = {
        "entryPoints": {
            "web": {
                "address": f":{DEFAULT_PORT}"
            }
        },
        "providers": {
            "file": {
                "filename": DYNAMIC_FILE
            }
        },
        "api": {
            "dashboard": True,
            "insecure": True
        }
    }
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(traefik_config, f)

    # Create dynamic.yml
    dynamic_config = {
        "http": {
            "routers": {},
            "services": {}
        }
    }
    with open(DYNAMIC_FILE, "w") as f:
        yaml.dump(dynamic_config, f)

    # Create tunnels file
    if not os.path.exists(TUNNELS_FILE):
        open(TUNNELS_FILE, "w").close()

# Function to create systemd service
def create_systemd_service():
    service_content = f"""
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
    with open(SERVICE_FILE, "w") as f:
        f.write(service_content)

    run_command(["sudo", "systemctl", "daemon-reload"])
    run_command(["sudo", "systemctl", "enable", "traefik-tunnel.service"])
    run_command(["sudo", "systemctl", "start", "traefik-tunnel.service"])

# Function to add a tunnel
def add_tunnel():
    frontend_port = input("Enter frontend port: ")
    backend_ip = input("Enter backend IP address (e.g., 192.168.1.100 or 2001:db8::1): ")
    backend_port = input("Enter backend port: ")

    # Check if frontend port is available
    if is_port_in_use(int(frontend_port)):
        print(f"Port {frontend_port} is already in use. Please choose another port.")
        return

    # Add tunnel to tunnels file
    with open(TUNNELS_FILE, "a") as f:
        f.write(f"{frontend_port} {backend_ip}:{backend_port}\n")

    # Update dynamic config
    update_dynamic_config()

    # Restart Traefik service
    run_command(["sudo", "systemctl", "restart", "traefik-tunnel.service"])

    print("Tunnel added successfully.")

# Function to delete a tunnel
def delete_tunnel():
    frontend_port = input("Enter frontend port to delete: ")

    # Remove tunnel from tunnels file
    with open(TUNNELS_FILE, "r") as f:
        lines = f.readlines()
    with open(TUNNELS_FILE, "w") as f:
        for line in lines:
            if not line.startswith(frontend_port):
                f.write(line)

    # Update dynamic config
    update_dynamic_config()

    # Restart Traefik service
    run_command(["sudo", "systemctl", "restart", "traefik-tunnel.service"])

    print("Tunnel deleted successfully.")

# Function to update dynamic config
def update_dynamic_config():
    with open(TUNNELS_FILE, "r") as f:
        tunnels = f.readlines()

    dynamic_config = {
        "http": {
            "routers": {},
            "services": {}
        }
    }

    for tunnel in tunnels:
        frontend_port, backend = tunnel.strip().split()
        router_name = f"router_{frontend_port}"
        service_name = f"service_{frontend_port}"

        dynamic_config["http"]["routers"][router_name] = {
            "entryPoints": ["web"],
            "service": service_name,
            "rule": "Host(`localhost`) && PathPrefix(`/`)"
        }

        dynamic_config["http"]["services"][service_name] = {
            "loadBalancer": {
                "servers": [
                    {"url": f"http://{backend}"}
                ]
            }
        }

    with open(DYNAMIC_FILE, "w") as f:
        yaml.dump(dynamic_config, f)

# Function to check if a port is in use
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

# Function to view tunnels
def view_tunnels():
    if not os.path.exists(TUNNELS_FILE) or os.path.getsize(TUNNELS_FILE) == 0:
        print("No tunnels found.")
    else:
        with open(TUNNELS_FILE, "r") as f:
            tunnels = f.readlines()
        print("=======================")
        print(" Forwarding Rules (Tunnels)")
        print("=======================")
        for i, tunnel in enumerate(tunnels, start=1):
            frontend_port, backend = tunnel.strip().split()
            print(f"{i} | Frontend Port: {frontend_port} | Backend: {backend}")
        print("=======================")

# Function to handle command-line arguments
def main():
    parser = argparse.ArgumentParser(description="Manage Traefik tunnels.")
    parser.add_argument("--view-tunnels", action="store_true", help="View all tunnels")
    parser.add_argument("--add-tunnel", action="store_true", help="Add a new tunnel")
    parser.add_argument("--delete-tunnel", action="store_true", help="Delete a tunnel")
    parser.add_argument("--start-service", action="store_true", help="Start Traefik service")
    parser.add_argument("--stop-service", action="store_true", help="Stop Traefik service")
    parser.add_argument("--restart-service", action="store_true", help="Restart Traefik service")
    parser.add_argument("--check-status", action="store_true", help="Check Traefik service status")
    parser.add_argument("--install", action="store_true", help="Install Traefik and setup tunnel")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall Traefik and tunnel")
    args = parser.parse_args()

    if args.view_tunnels:
        view_tunnels()
    elif args.add_tunnel:
        add_tunnel()
    elif args.delete_tunnel:
        delete_tunnel()
    elif args.start_service:
        run_command(["sudo", "systemctl", "start", "traefik-tunnel.service"])
        print("Traefik tunnel service started.")
    elif args.stop_service:
        run_command(["sudo", "systemctl", "stop", "traefik-tunnel.service"])
        print("Traefik tunnel service stopped.")
    elif args.restart_service:
        run_command(["sudo", "systemctl", "restart", "traefik-tunnel.service"])
        print("Traefik tunnel service restarted.")
    elif args.check_status:
        run_command(["sudo", "systemctl", "status", "traefik-tunnel.service"])
    elif args.install:
        install_traefik()
        create_config_files()
        create_systemd_service()
        print("Traefik tunnel service installed and started.")
    elif args.uninstall:
        run_command(["sudo", "systemctl", "stop", "traefik-tunnel.service"])
        run_command(["sudo", "systemctl", "disable", "traefik-tunnel.service"])
        if os.path.exists(SERVICE_FILE):
            os.remove(SERVICE_FILE)
        if os.path.exists(CONFIG_DIR):
            run_command(["sudo", "rm", "-rf", CONFIG_DIR])
        run_command(["sudo", "systemctl", "daemon-reload"])
        print("Traefik tunnel service uninstalled.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
