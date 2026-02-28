#!/usr/bin/env bash
# setup.sh — Interactive installer for Pie-Brain
# This installer executes remote code. Review before running in production.
# Usage: bash setup.sh
#        curl -fsSL https://raw.githubusercontent.com/AlexMcLeod0/Pie-Brain/main/setup.sh | bash
set -euo pipefail
shopt -s nullglob

# ─── TTY guard ────────────────────────────────────────────────────────────────
# When the script is fed through a pipe (e.g. curl | bash) bash reads the
# script from stdin.  Any `read` built-in would then consume lines from the
# *script itself* rather than from the keyboard, causing prompts to be skipped
# and downstream syntax errors.  Redirect stdin to the real terminal early so
# every `read` talks to the user, not the pipe.
if [[ ! -t 0 ]]; then
    if [[ ! -e /dev/tty ]]; then
        echo "[✗] This installer needs an interactive terminal." >&2
        echo "    Download setup.sh and run it directly: bash setup.sh" >&2
        exit 1
    fi
    exec </dev/tty
fi

# ─── Colours & helpers ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}[•]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
die()     { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }

# ─── Banner ───────────────────────────────────────────────────────────────────
echo -e "${CYAN}${BOLD}"
cat << 'BANNER'
  ____  _        ____            _
 |  _ \(_) ___  | __ ) _ __ __ _(_)_ __
 | |_) | |/ _ \ |  _ \| '__/ _` | | '_ \
 |  __/| |  __/ | |_) | | | (_| | | | | |
 |_|   |_|\___| |____/|_|  \__,_|_|_| |_|

 Modular async task-routing engine for Raspberry Pi
BANNER
echo -e "${RESET}"

REPO_URL="https://github.com/AlexMcLeod0/Pie-Brain.git"
DEFAULT_INSTALL_DIR="${HOME}/pie-brain"

# ─── Prerequisite checks ──────────────────────────────────────────────────────
info "Checking prerequisites…"

check_cmd() { command -v "$1" &>/dev/null || die "Required tool '$1' not found. Please install it and re-run."; }

check_cmd git
check_cmd python3
check_cmd curl

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [[ $PY_MAJOR -lt 3 || ($PY_MAJOR -eq 3 && $PY_MINOR -lt 11) ]]; then
    die "Python 3.11+ required (found ${PY_MAJOR}.${PY_MINOR}). Install via pyenv or your package manager."
fi
success "Python ${PY_MAJOR}.${PY_MINOR} found."

if ! command -v ollama &>/dev/null; then
    warn "ollama not found — required at runtime. Install later: https://ollama.ai"
fi

# ─── Install uv if needed ─────────────────────────────────────────────────────
UV_BIN=""
if command -v uv &>/dev/null; then
    UV_BIN="$(command -v uv)"
elif [[ -x "${HOME}/.local/bin/uv" ]]; then
    UV_BIN="${HOME}/.local/bin/uv"
else
    info "Installing uv package manager…"
    tmp_uv="$(mktemp)"
    curl -LsSf https://astral.sh/uv/install.sh -o "$tmp_uv"
    sh "$tmp_uv"
    rm -f "$tmp_uv"
    UV_BIN="${HOME}/.local/bin/uv"
fi
export PATH="${HOME}/.local/bin:${PATH}"
[[ -x "$UV_BIN" ]] || die "uv installation failed."

# ─── Install directory ────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Where should Pie-Brain be installed?${RESET}"
read -rp "  Directory [${DEFAULT_INSTALL_DIR}]: " INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

if [[ -d "$INSTALL_DIR" ]]; then
    warn "Directory '${INSTALL_DIR}' already exists."
    read -rp "  Remove and reinstall? [y/N]: " _ow
    case "$_ow" in
        y|Y) ;;
        *) die "Aborting. Choose a different directory or remove it manually." ;;
    esac
    [[ -n "$INSTALL_DIR" && "$INSTALL_DIR" != "/" ]] || die "Refusing to remove unsafe directory."
    rm -rf "$INSTALL_DIR"
fi

# ─── Brain provider ───────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Choose a brain provider:${RESET}"
echo "  1) Claude Code  — Spawns the 'claude' CLI for cloud tasks  [default]"
echo "  (Additional providers can be added to brains/ and will appear here)"
echo
read -rp "  Enter choice [1]: " _brain_num
case "${_brain_num:-1}" in
    1) BRAIN="claude_code" ;;
    *) die "Invalid choice '${_brain_num}'." ;;
esac
success "Brain provider: ${BRAIN}"

if [[ "$BRAIN" == "claude_code" ]] && ! command -v claude &>/dev/null; then
    warn "'claude' CLI not found — authenticate it before running the engine."
fi

# ─── Messaging provider ───────────────────────────────────────────────────────
echo
echo -e "${BOLD}Choose a messaging provider:${RESET}"
echo "  1) Telegram  — Receive and reply to tasks via a Telegram bot  [default]"
echo "  2) None      — Scheduler-only mode (no interactive messaging)"
echo "  (Additional providers can be added to providers/ and will appear here)"
echo
read -rp "  Enter choice [1]: " _prov_num
case "${_prov_num:-1}" in
    1) PROVIDER="telegram" ;;
    2) PROVIDER="none" ;;
    *) die "Invalid choice '${_prov_num}'." ;;
esac
success "Messaging provider: ${PROVIDER}"

# ─── Tool selection ───────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Which tools should be installed?${RESET}"
echo "  Enter space-separated numbers, 'all', or 'none'."
echo
echo "  1) arxiv     — ArXiv paper search and daily discovery"
echo "  2) memory    — Persistent vector memory with deduplication (LanceDB)"
echo "  3) git_sync  — Git repo sync and PR creation  (requires git + gh CLI)"
echo
read -rp "  Choices [all]: " _tools_input
_tools_input="${_tools_input:-all}"

TOOLS=()
if [[ "$_tools_input" == "none" ]]; then
    :
elif [[ "$_tools_input" == "all" ]]; then
    TOOLS=(arxiv memory git_sync)
else
    for _n in $_tools_input; do
        case "$_n" in
            1) TOOLS+=(arxiv) ;;
            2) TOOLS+=(memory) ;;
            3) TOOLS+=(git_sync) ;;
            *) warn "Unknown tool number '${_n}', skipping." ;;
        esac
    done
fi
success "Tools: ${TOOLS[*]:-none}"

if [[ " ${TOOLS[*]} " == *" git_sync "* ]] && ! command -v gh &>/dev/null; then
    warn "'gh' CLI not found — required by git_sync. Install: https://cli.github.com"
fi

# ─── Clone repository ─────────────────────────────────────────────────────────
echo
info "Cloning repository into ${INSTALL_DIR}…"
tmp_dir="$(mktemp -d)"
git clone --depth 1 "$REPO_URL" "$tmp_dir"
rsync -a --delete "$tmp_dir/" "$INSTALL_DIR/"
rm -rf "$tmp_dir"
cd "$INSTALL_DIR"

# ─── Prune unselected files ───────────────────────────────────────────────────
# The auto-discovery registries (tools/__init__.py, brains/registry.py) use
# pkgutil.iter_modules, so absent files are simply never loaded.
info "Removing unneeded files for selected configuration…"

# Brains — remove all except the chosen one
for _f in brains/*.py; do
    _mod="$(basename "$_f" .py)"
    [[ "$_mod" == "__init__" || "$_mod" == "base" || "$_mod" == "registry" ]] && continue
    [[ "$_mod" == "$BRAIN" ]] && continue
    rm -f "$_f" && info "  removed brains/${_mod}.py"
done

# Providers — remove messaging provider file if 'none' was selected
if [[ "$PROVIDER" == "none" ]]; then
    rm -f providers/telegram.py && info "  removed providers/telegram.py"
fi

# Tools — remove any tool not in TOOLS list
for _f in tools/*.py; do
    _stem="$(basename "$_f" .py)"
    [[ "$_stem" == "__init__" ]] && continue
    _keep=0
    for _t in "${TOOLS[@]}"; do
      if [[ "$_t" == "$_stem" ]]; then
        _keep=1
        break
      fi
    done

    if [[ $_keep -eq 0 ]]; then
      rm -f "tools/${_stem}.py" "tools/${_stem}_runner.py"
      info "  removed tools/${_stem}.py and tools/${_stem}_runner.py"
    fi
done

success "Repository trimmed to selected modules."

# ─── Build extras list & install dependencies ─────────────────────────────────
echo
info "Installing Python dependencies…"

EXTRAS=()
[[ "$PROVIDER" == "telegram" ]]              && EXTRAS+=(telegram)
[[ " ${TOOLS[*]} " == *" arxiv "* ]]         && EXTRAS+=(arxiv)
[[ " ${TOOLS[*]} " == *" memory "* ]]        && EXTRAS+=(memory)

if [[ ${#EXTRAS[@]} -gt 0 ]]; then
    _extra_args=()
    for _e in "${EXTRAS[@]}"; do _extra_args+=(--extra "$_e"); done
    "$UV_BIN" sync "${_extra_args[@]}" || die "Dependency installation failed."
else
    "$UV_BIN" sync || die "Dependency installation failed."
fi
success "Dependencies installed."

# ─── Collect runtime configuration ────────────────────────────────────────────
echo
echo -e "${BOLD}── Runtime configuration ──${RESET}"
echo

read -rp "  Ollama router model [qwen2.5:1.5b]: " _ollama_model
OLLAMA_MODEL="${_ollama_model:-qwen2.5:1.5b}"

TELEGRAM_TOKEN=""
TELEGRAM_ALLOWED=""
if [[ "$PROVIDER" == "telegram" ]]; then
    echo
    echo -e "${BOLD}Telegram:${RESET}"
    read -rp "  Bot token (from @BotFather): " TELEGRAM_TOKEN
    read -rp "  Allowed user IDs, comma-separated (blank = allow anyone): " TELEGRAM_ALLOWED
fi

ARXIV_KEYWORDS=""
if [[ " ${TOOLS[*]} " == *" arxiv "* ]]; then
    echo
    echo "  ArXiv discovery keywords, comma-separated"
    read -rp "  [large language models,reinforcement learning]: " _kw
    ARXIV_KEYWORDS="${_kw:-large language models,reinforcement learning}"
fi

# ─── Create runtime directories ───────────────────────────────────────────────
info "Creating runtime directories…"
mkdir -p "${HOME}/.pie-brain/logs"
mkdir -p "${HOME}/brain/inbox"
mkdir -p "${HOME}/brain/profile"

if [[ ! -f "${HOME}/brain/profile/user_prefs.md" ]]; then
    cat > "${HOME}/brain/profile/user_prefs.md" << 'EOF'
# User Preferences

This file is prepended to every routing prompt. Add personal context here.

Examples:
- Prefer concise summaries (3–5 bullet points).
- Write output in British English.
- For ArXiv papers, focus on practical applications over theory.
EOF
    success "Created starter ~/brain/profile/user_prefs.md"
fi

# ─── Write .env ───────────────────────────────────────────────────────────────
info "Writing .env…"
ENV_FILE="${INSTALL_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%s)"
fi
{
    echo "# Pie-Brain configuration — generated by setup.sh"
    echo "DEFAULT_CLOUD_BRAIN=${BRAIN}"
    echo "OLLAMA_MODEL=${OLLAMA_MODEL}"
    [[ -n "$TELEGRAM_TOKEN" ]]   && echo "TELEGRAM_BOT_TOKEN=${TELEGRAM_TOKEN}"
    [[ -n "$TELEGRAM_ALLOWED" ]] && echo "TELEGRAM_ALLOWED_USER_IDS=${TELEGRAM_ALLOWED}"
    if [[ -n "$ARXIV_KEYWORDS" ]]; then
        # Convert "a, b, c" → JSON array for pydantic-settings
        _kw_json=$(python3 -c \
            "import json,sys; kw=sys.argv[1].split(','); print(json.dumps([k.strip() for k in kw]))" \
            "$ARXIV_KEYWORDS")
        echo "ARXIV_DISCOVER_KEYWORDS=${_kw_json}"
    fi
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
success ".env written to ${ENV_FILE}"

# ─── Optional systemd user service ────────────────────────────────────────────
echo
if command -v systemctl &>/dev/null; then
    read -rp "  Install systemd user service (auto-start on login)? [y/N]: " _svc
   case "$_svc" in
    y|Y)
      _svc_dir="${HOME}/.config/systemd/user"
      mkdir -p "$_svc_dir"
      cat > "${_svc_dir}/pie-brain.service" << EOF
[Unit]
Description=Pie-Brain task routing engine
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${UV_BIN} run --directory ${INSTALL_DIR} python -m core.engine
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

            systemctl --user daemon-reload
            systemctl --user enable pie-brain.service
            success "Service installed. Start with: systemctl --user start pie-brain"
            ;;
    esac
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Pie-Brain installation complete!${RESET}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════${RESET}"
echo
printf "  %-18s %s\n" "Installed to:"   "${INSTALL_DIR}"
printf "  %-18s %s\n" "Brain provider:" "${BRAIN}"
printf "  %-18s %s\n" "Messaging:"      "${PROVIDER}"
printf "  %-18s %s\n" "Tools:"          "${TOOLS[*]:-none}"
echo
echo -e "${BOLD}Next steps:${RESET}"
echo "  1. Pull your Ollama model:     ollama pull ${OLLAMA_MODEL}"
[[ "$BRAIN" == "claude_code" ]] && \
echo "  2. Authenticate Claude Code:   claude login"
echo "  3. Start the engine:"
case "${_svc:-}" in
    y|Y)
echo "       systemctl --user start pie-brain"
        ;;
    *)
echo "       cd ${INSTALL_DIR} && ${UV_BIN} run python -m core.engine"
        ;;
esac
echo "  4. Edit user preferences:      ${HOME}/brain/profile/user_prefs.md"
echo "  5. Adjust settings:            ${INSTALL_DIR}/.env"
echo
