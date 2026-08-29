#!/usr/bin/env bash
# Install Graph RCA — Python env, dependencies, and optional repo index
# Usage: ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "╔══════════════════════════════════════════╗"
echo "║   Graph RCA — Install                    ║"
echo "╚══════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}[1/4] Checking & installing prerequisites...${NC}"

if command -v python3 &> /dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "  ✓ Python $PY_VER"
else
    echo -e "${RED}  ✗ Python 3.11+ required. Install from https://python.org or: brew install python@3.13${NC}"
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}  Installing uv (Python package manager)...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "  ✓ uv $(uv --version 2>/dev/null | head -1)"

if ! command -v pipx &> /dev/null; then
    echo -e "${YELLOW}  Installing pipx...${NC}"
    if command -v brew &> /dev/null; then
        brew install pipx
        pipx ensurepath
    else
        python3 -m pip install --user pipx
        python3 -m pipx ensurepath
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "  ✓ pipx found"

if ! command -v codegraphcontext &> /dev/null; then
    echo -e "${YELLOW}  Installing codegraphcontext (code graph indexer)...${NC}"
    pipx install codegraphcontext 2>&1 | tail -2 | sed 's/^/    /'
fi
echo "  ✓ codegraphcontext $(codegraphcontext --version 2>/dev/null || echo 'installed')"

if ! command -v dot &> /dev/null; then
    echo -e "${YELLOW}  Installing graphviz (for SVG visualization)...${NC}"
    if command -v brew &> /dev/null; then
        brew install graphviz 2>&1 | tail -1 | sed 's/^/    /'
    elif command -v apt-get &> /dev/null; then
        sudo apt-get install -y graphviz 2>&1 | tail -1 | sed 's/^/    /'
    else
        echo -e "${YELLOW}  ⚠ Install graphviz manually: https://graphviz.org/download/${NC}"
    fi
fi
if command -v dot &> /dev/null; then
    echo "  ✓ graphviz (dot)"
fi

echo ""
echo -e "${GREEN}[2/4] Setting up Python environment...${NC}"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "  Creating virtual environment..."
    uv venv
fi
echo "  ✓ Virtual environment: .venv/"

echo "  Installing packages..."
uv sync 2>&1 | tail -3 | sed 's/^/    /'
echo "  ✓ All dependencies installed"

uv run python -c "
import sentence_transformers, scipy, yaml, falkordb
print('  ✓ sentence-transformers, scipy, pyyaml, falkordb — OK')
" 2>/dev/null || echo -e "${YELLOW}  ⚠ Some packages may need manual install${NC}"

echo ""
echo -e "${GREEN}[3/4] Checking AWS credentials (Bedrock access)...${NC}"
if command -v aws &> /dev/null; then
    AWS_ID=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null || echo "")
    if [ -n "$AWS_ID" ]; then
        echo "  ✓ AWS authenticated (account: $AWS_ID)"
    else
        echo -e "${YELLOW}  ⚠ AWS credentials not configured or expired${NC}"
        echo "    Set up with: aws configure"
        echo "    Or export AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY"
        echo "    Or set CLOUD_PROVIDER=ollama and use configs/runtime/ollama.yaml"
    fi
else
    echo -e "${YELLOW}  ⚠ AWS CLI not found. Install: brew install awscli${NC}"
    echo "    Required for Bedrock. Or set CLOUD_PROVIDER=ollama."
fi

echo ""
echo -e "${GREEN}[4/4] Optional: index a source repo${NC}"
echo "Graph RCA needs an indexed repo + a domain YAML before it can analyze logs."
echo ""
read -p "Index a repo now? [y/N]: " SETUP_RCA

if [[ "$SETUP_RCA" =~ ^[Yy]$ ]]; then
    echo ""
    echo "  Enter the path to your source code repository:"
    read -p "  Repo path: " REPO_PATH
    REPO_PATH="${REPO_PATH/#\~/$HOME}"

    if [ ! -d "$REPO_PATH" ]; then
        echo -e "${RED}  ✗ Directory not found: $REPO_PATH${NC}"
        exit 1
    fi

    REPO_NAME=$(basename "$REPO_PATH")
    echo "  Repo name: $REPO_NAME"

    GROOVY_COUNT=$(find "$REPO_PATH" -name "*.groovy" | head -10 | wc -l | tr -d ' ')
    PS_COUNT=$(find "$REPO_PATH" -name "*.ps1" -o -name "*.psm1" | head -10 | wc -l | tr -d ' ')
    if [ "$GROOVY_COUNT" -gt 0 ] || [ "$PS_COUNT" -gt 0 ]; then
        echo ""
        echo -e "  ${YELLOW}Groovy/PowerShell detected — patching codegraphcontext...${NC}"
        uv run python -c "from src.main.graph_rca.lang_support.patch_codegraphcontext import patch; patch()" 2>&1 | sed 's/^/    /'
        echo -e "  ${GREEN}✓ Patched${NC}"
    fi

    echo ""
    echo -e "${GREEN}  Indexing (codegraph + lite index + flow graphs)...${NC}"
    uv run graph-rca index --repo "$REPO_PATH" --name "$REPO_NAME"

    echo ""
    echo "  Choose a base log format for your config:"
    echo "    1) Spring Boot (Java/Groovy — Logback default)"
    echo "    2) Python logging (stdlib)"
    echo "    3) Go structured (JSON)"
    echo "    4) Skip (I'll create my own)"
    read -p "  Choice [1-4]: " FORMAT_CHOICE

    CONFIG_PATH="configs/$REPO_NAME.yaml"
    case $FORMAT_CHOICE in
        1) BASE="base/spring-boot.yaml" ;;
        2) BASE="base/python-logging.yaml" ;;
        3) BASE="base/go-structured.yaml" ;;
        4) BASE="" ;;
        *) BASE="base/spring-boot.yaml" ;;
    esac

    if [ -n "$BASE" ]; then
        cat > "$SCRIPT_DIR/$CONFIG_PATH" << CFGEOF
# $REPO_NAME — Domain Config
# Generated by install.sh. Edit as needed.
# Full reference: docs/wiki/code-rca-get-started.md

extends: $BASE

repo: $REPO_NAME
service_name: $REPO_NAME

ignore_patterns:
  - 'GET /healthz'
  - 'GET /actuator'

error_markers:
  - pattern: 'Exception'
  - pattern: 'ERROR'
CFGEOF
        echo "  ✓ Config created: $CONFIG_PATH"
        echo -e "  ${YELLOW}Hint: Edit ignore_patterns and error_markers for your app${NC}"
    else
        echo "  Skipped. Create your config at configs/$REPO_NAME.yaml"
        echo "  See configs/base/ for templates."
        CONFIG_PATH="configs/<repo-name>.yaml"
    fi

    echo ""
    echo -e "${GREEN}  Ready.${NC}"
    echo ""
    echo "  Run analysis:"
    echo "    uv run graph-rca run \\"
    echo "      --log /path/to/your/app.log \\"
    echo "      --repo $REPO_PATH \\"
    echo "      --config $CONFIG_PATH \\"
    echo "      --verbose"
else
    echo ""
    echo "  Skipped. Index later with:"
    echo "    uv run graph-rca index --repo /path/to/repo --name <repo-name>"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Quick Reference                                            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  # Index"
echo "  uv run graph-rca index --repo /path/to/repo --name <repo-name>"
echo ""
echo "  # RCA on a log"
echo "  uv run graph-rca run --log /path/to/app.log --repo <repo> --config configs/<name>.yaml --verbose"
echo ""
echo "  # Query (no log)"
echo "  uv run graph-rca query \"how does provisioning work\" --repo <name> --config configs/<name>.yaml"
echo ""
echo "  Full guide: docs/wiki/code-rca-get-started.md"
echo ""
