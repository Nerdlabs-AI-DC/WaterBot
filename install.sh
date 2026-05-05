set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Helpers
print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓  $1${NC}"
}

print_error() {
    echo -e "${RED}✗  $1${NC}"
}

print_info() {
    echo -e "${YELLOW}•  $1${NC}"
}

# Installation
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

print_header "WaterBot Installation"

print_info "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    print_error "Python 3.10 or higher required (found $PYTHON_VERSION)"
    exit 1
fi
print_success "Python $PYTHON_VERSION found"

print_info "Creating virtual environment..."
if [ -d ".venv" ]; then
    print_info "Virtual environment already exists at .venv"
else
    python3 -m venv .venv
    print_success "Virtual environment created"
fi

print_info "Activating virtual environment..."
source .venv/bin/activate
print_success "Virtual environment activated"

print_info "Upgrading pip..."
pip install --upgrade pip --no-cache-dir --quiet
print_success "pip upgraded"

print_info "Installing WaterBot..."
pip install -e . --no-cache-dir --quiet
print_success "WaterBot installed"

print_info "Creating symlink..."

mkdir -p ~/.local/bin

WATERBOT_SCRIPT="$(pwd)/waterbot"
SYMLINK_TARGET="$HOME/.local/bin/waterbot"

if [ -L "$SYMLINK_TARGET" ]; then
    rm "$SYMLINK_TARGET"
fi

ln -s "$WATERBOT_SCRIPT" "$SYMLINK_TARGET"
chmod +x "$WATERBOT_SCRIPT"

if [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
    print_success "Created symlink"
else
    print_info "Error creating symlink: ~/.local/bin is not in your PATH"
    print_info "To add ~/.local/bin to your PATH, add this line to ~/.bashrc or ~/.zshrc:"
    echo -e "    ${BLUE}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
    print_info "Then reload your shell: ${BLUE}source ~/.bashrc${NC} or ${BLUE}source ~/.zshrc${NC}"
fi

print_header "Installation Complete!"

echo ""
print_info "To start WaterBot, run:"
echo -e "    ${BLUE}waterbot${NC}"

print_info "To stop WaterBot, press ${BLUE}Ctrl+C${NC}"

echo ""
print_success "Successfully installed WaterBot!"
echo ""
