#!/bin/bash

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://raw.githubusercontent.com/Salarvand-Education/AS-Tunnel/main/install.py"
SCRIPT_NAME="install.py"
VENV_NAME="tunnel_venv"
DEFAULT_API_PORT=8081
CONFIG_FILE="/etc/traefik/api_port.conf"

# Initialize API port
if [ -f "$CONFIG_FILE" ]; then
    API_PORT=$(cat "$CONFIG_FILE")
else
    API_PORT=$DEFAULT_API_PORT
fi

# Error handling
set -e
trap 'handle_error $? $LINENO' ERR

handle_error() {
    local exit_code=$1
    local line_number=$2
    echo -e "${RED}Error occurred in script at line $line_number. Exit code: $exit_code${NC}"
    cleanup
    exit 1
}

cleanup() {
    echo -e "${YELLOW}Performing cleanup...${NC}"
    deactivate 2>/dev/null || true
}

# Clear screen function
clear_screen() {
    clear
}

# Print header function
print_header() {
    echo -e "${CYAN}"
    echo "╔════════════════════════════════════╗"
    echo "║        Traefik Tunnel Manager      ║"
    echo "╚════════════════════════════════════╝"
    echo -e "${NC}"
}

# Print menu function
print_menu() {
    echo -e "${YELLOW}1. Install New Tunnel"
    echo "2. Delete Existing Tunnels"
    echo "3. Display Tunnel Status"
    echo "4. Start Tunnel Monitor"
    echo "5. Uninstall Service"
    echo "6. Update Source File"
    echo "7. Configure API Port"
    echo -e "0. Exit${NC}"
}

# Check sudo access
check_sudo() {
    if ! sudo -v &>/dev/null; then
        echo -e "${RED}Error: This script requires sudo privileges${NC}"
        exit 1
    fi
}

# Configure API port
configure_api_port() {
    echo -e "${CYAN}=== Configure API Port ===${NC}"
    echo -e "Current API port: $API_PORT"
    echo -e "Enter new API port (1024-65535, default is ${DEFAULT_API_PORT}):"
    read -r new_port
    
    if [[ "$new_port" =~ ^[0-9]+$ && "$new_port" -ge 1024 && "$new_port" -le 65535 ]]; then
        # Save the new port to config file
        echo "$new_port" | sudo tee "$CONFIG_FILE" > /dev/null
        API_PORT=$new_port
        echo -e "${GREEN}API port updated to: $API_PORT${NC}"
        
        # Restart service if it exists
        if [ -f "/etc/systemd/system/traefik-tunnel.service" ]; then
            echo -e "${YELLOW}Restarting Traefik service...${NC}"
            sudo systemctl restart traefik-tunnel.service
        fi
    else
        echo -e "${RED}Invalid port number. Using default: ${DEFAULT_API_PORT}${NC}"
        API_PORT=$DEFAULT_API_PORT
    fi
}

# Check and install system dependencies
check_system_dependencies() {
    echo -e "${BLUE}Checking system dependencies...${NC}"
    
    local packages=("curl" "python3" "python3-pip" "python3-venv")
    local missing_packages=()
    
    for pkg in "${packages[@]}"; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            missing_packages+=("$pkg")
        fi
    done
    
    if [ ${#missing_packages[@]} -ne 0 ]; then
        echo -e "${YELLOW}Installing missing packages: ${missing_packages[*]}${NC}"
        sudo apt update
        sudo apt install -y "${missing_packages[@]}"
    fi
}

# Download source file
download_source() {
    echo -e "${BLUE}Downloading source file from GitHub...${NC}"
    
    if curl -# -o "$SCRIPT_NAME" "$REPO_URL"; then
        echo -e "${GREEN}Successfully downloaded $SCRIPT_NAME${NC}"
        chmod +x "$SCRIPT_NAME"
    else
        echo -e "${RED}Failed to download source file${NC}"
        exit 1
    fi
}

# Setup virtual environment
setup_venv() {
    echo -e "${BLUE}Setting up virtual environment...${NC}"
    
    if [ ! -d "$VENV_NAME" ]; then
        python3 -m venv "$VENV_NAME"
    fi
    
    source "$VENV_NAME/bin/activate"
    python3 -m pip install --upgrade pip
    
    echo -e "${BLUE}Installing required Python packages...${NC}"
    pip install termcolor requests pyyaml tqdm
}

# Check if Python script exists
check_script() {
    if [ ! -f "$SCRIPT_NAME" ]; then
        download_source
    fi
}

# Run Python script in virtual environment
run_python_script() {
    source "$VENV_NAME/bin/activate"
    python3 "$@" "$API_PORT"
    deactivate
}

# Main menu loop
main_menu() {
    while true; do
        clear_screen
        print_header
        print_menu
        
        echo -e "\n${GREEN}Current API Port: ${API_PORT}${NC}"
        echo -e "${GREEN}Please select an option:${NC} "
        read -r choice
        
        case $choice in
            1)
                clear_screen
                print_header
                echo -e "${CYAN}=== Install New Tunnel ===${NC}\n"
                run_python_script "$SCRIPT_NAME" install
                echo -e "\n${YELLOW}Press Enter to return to menu...${NC}"
                read -r
                ;;
            2)
                clear_screen
                print_header
                echo -e "${CYAN}=== Delete Existing Tunnels ===${NC}\n"
                run_python_script "$SCRIPT_NAME" delete
                echo -e "\n${YELLOW}Press Enter to return to menu...${NC}"
                read -r
                ;;
            3)
                clear_screen
                print_header
                echo -e "${CYAN}=== Tunnel Status ===${NC}\n"
                run_python_script "$SCRIPT_NAME" status
                echo -e "\n${YELLOW}Press Enter to return to menu...${NC}"
                read -r
                ;;
            4)
                clear_screen
                print_header
                echo -e "${CYAN}=== Start Tunnel Monitor ===${NC}\n"
                run_python_script "$SCRIPT_NAME" monitor
                echo -e "\n${YELLOW}Press Enter to return to menu...${NC}"
                read -r
                ;;
            5)
                clear_screen
                print_header
                echo -e "${CYAN}=== Uninstall Service ===${NC}\n"
                echo -e "${RED}Are you sure you want to uninstall the service? (y/n):${NC} "
                read -r confirm
                if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
                    run_python_script "$SCRIPT_NAME" uninstall
                fi
                echo -e "\n${YELLOW}Press Enter to return to menu...${NC}"
                read -r
                ;;
            6)
                clear_screen
                print_header
                echo -e "${CYAN}=== Update Source File ===${NC}\n"
                download_source
                echo -e "\n${YELLOW}Press Enter to return to menu...${NC}"
                read -r
                ;;
            7)
                clear_screen
                print_header
                configure_api_port
                echo -e "\n${YELLOW}Press Enter to return to menu...${NC}"
                read -r
                ;;
            0)
                echo -e "\n${RED}Exiting...${NC}"
                cleanup
                exit 0
                ;;
            *)
                echo -e "\n${RED}Invalid option! Please try again.${NC}"
                sleep 2
                ;;
        esac
    done
}

# Handle Ctrl+C
trap 'echo -e "\n${YELLOW}Program terminated by user${NC}"; cleanup; exit 0' SIGINT

# Main execution
check_sudo
check_system_dependencies
check_script
setup_venv
main_menu
