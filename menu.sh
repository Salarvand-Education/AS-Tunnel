#!/bin/bash

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# GitHub repository details
REPO_URL="https://raw.githubusercontent.com/Salarvand-Education/AS-Tunnel/main/install.py"
SCRIPT_NAME="install.py"

# Virtual environment name
VENV_NAME="tunnel_venv"

# Required packages
PACKAGES=(
    "termcolor"
    "requests"
    "pyyaml"
    "tqdm"
)

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
    echo "4. List Active Tunnels"
    echo "5. Uninstall Service"
    echo "6. Update Source File"
    echo -e "0. Exit${NC}"
}

# Download source file
download_source() {
    echo -e "${BLUE}Downloading source file from GitHub...${NC}"
    if curl -sSL "$REPO_URL" -o "$SCRIPT_NAME"; then
        echo -e "${GREEN}Successfully downloaded $SCRIPT_NAME${NC}"
    else
        echo -e "${RED}Failed to download source file${NC}"
        exit 1
    fi
}

# Check and install system dependencies
check_system_dependencies() {
    echo -e "${BLUE}Checking system dependencies...${NC}"
    
    # Check for curl
    if ! command -v curl &> /dev/null; then
        echo -e "${YELLOW}Installing curl...${NC}"
        sudo apt update
        sudo apt install -y curl
    fi

    # Check for Python3
    if ! command -v python3 &> /dev/null; then
        echo -e "${YELLOW}Installing Python3...${NC}"
        sudo apt update
        sudo apt install -y python3
    fi

    # Check for pip
    if ! command -v pip3 &> /dev/null; then
        echo -e "${YELLOW}Installing pip3...${NC}"
        sudo apt install -y python3-pip
    fi

    # Check for python3-venv
    if ! dpkg -l | grep -q python3-venv; then
        echo -e "${YELLOW}Installing python3-venv...${NC}"
        sudo apt install -y python3-venv
    fi
}

# Setup virtual environment
setup_venv() {
    echo -e "${BLUE}Setting up virtual environment...${NC}"
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "$VENV_NAME" ]; then
        python3 -m venv "$VENV_NAME"
    fi
    
    # Activate virtual environment
    source "$VENV_NAME/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install required packages
    echo -e "${BLUE}Installing required Python packages...${NC}"
    for package in "${PACKAGES[@]}"; do
        pip install "$package"
    done
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
    python3 "$@"
    deactivate
}

# Main menu loop
main_menu() {
    while true; do
        clear_screen
        print_header
        print_menu
        
        echo -e "\n${GREEN}Please select an option:${NC} "
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
                echo -e "${CYAN}=== Active Tunnels List ===${NC}\n"
                run_python_script "$SCRIPT_NAME" list
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
            0)
                echo -e "\n${RED}Exiting...${NC}"
                deactivate 2>/dev/null || true
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
trap 'echo -e "\n${YELLOW}Program terminated by user${NC}"; deactivate 2>/dev/null || true; exit 0' SIGINT

# Main execution
check_system_dependencies
check_script
setup_venv
main_menu
