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

# Upsert KEY=VALUE in an .env file (portable: no sed -i differences)
update_env_var() {
    local key="$1" value="$2" file="$3"
    local tmp
    tmp="$(mktemp)"
    grep -v "^${key}=" "$file" 2>/dev/null > "$tmp" || true
    echo "${key}=${value}" >> "$tmp"
    mv "$tmp" "$file"
}

# Human-readable description for a tool stem name.
# Reads routing_description directly from the tool's Python source via ast —
# no hardcoded list needed; new tools are picked up automatically.
tool_description() {
    local f="tools/${1}.py"
    [[ -f "$f" ]] || { echo "no description available"; return; }
    python3 - "$f" <<'PYEOF'
import ast, sys
try:
    for node in ast.walk(ast.parse(open(sys.argv[1]).read())):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                for t in getattr(item, 'targets', []):
                    if (getattr(t, 'id', '') == 'routing_description'
                            and isinstance(getattr(item, 'value', None), ast.Constant)):
                        print(item.value.s); sys.exit(0)
except Exception:
    pass
print('no description available')
PYEOF
}

# Returns "true" if the tool Python file declares required = True.
# Required tools are always active and never offered to the user for removal.
# Accepts a file path (relative or absolute) so it works before cd into INSTALL_DIR.
tool_required() {
    [[ -f "$1" ]] || { echo "false"; return; }
    python3 - "$1" <<'PYEOF'
import ast, sys
try:
    for node in ast.walk(ast.parse(open(sys.argv[1]).read())):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                for t in getattr(item, 'targets', []):
                    if (getattr(t, 'id', '') == 'required'
                            and isinstance(getattr(item, 'value', None), ast.Constant)
                            and item.value.value is True):
                        print('true'); sys.exit(0)
except Exception:
    pass
print('false')
PYEOF
}

# uv extras flag needed for a tool's dependencies (empty = base deps only)
tool_extras() {
    case "$1" in
        arxiv)  echo "arxiv" ;;
        memory) echo "memory" ;;
        *)      echo "" ;;
    esac
}

# Join array elements with commas
join_comma() { local IFS=','; echo "$*"; }

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

MODE="install"
if [[ -d "$INSTALL_DIR" ]]; then
    warn "Directory '${INSTALL_DIR}' already exists."
    echo "  1) Update from source  — pull latest code, keep your settings  [default]"
    echo "  2) Remove and reinstall — clean install (overwrites settings)"
    echo "  3) Abort"
    echo
    read -rp "  Choice [1]: " _exist_choice
    case "${_exist_choice:-1}" in
        1) MODE="update" ;;
        2)
            [[ -n "$INSTALL_DIR" && "$INSTALL_DIR" != "/" ]] || die "Refusing to remove unsafe directory."
            rm -rf "$INSTALL_DIR"
            ;;
        *) die "Aborting." ;;
    esac
fi

# ─── Update path (early exit) ─────────────────────────────────────────────────
if [[ "$MODE" == "update" ]]; then
    echo
    info "Updating Pie-Brain in ${INSTALL_DIR}…"
    ENV_FILE="${INSTALL_DIR}/.env"

    # ── Snapshot state before the pull ──────────────────────────────────────
    # Which optional tool files are on disk right now?
    _installed_before=()
    for _f in "${INSTALL_DIR}/tools/"*.py; do
        [[ -f "$_f" ]] || continue
        _stem="$(basename "$_f" .py)"
        case "$_stem" in __init__|base|runner) continue ;; esac
        [[ "$(tool_required "$_f")" == "true" ]] && continue
        _installed_before+=("$_stem")
    done

    # Which tools did the user previously decline? (stored in .env)
    _declined_str="$(grep '^SETUP_DECLINED_TOOLS=' "$ENV_FILE" 2>/dev/null \
        | cut -d= -f2- | tr -d ' ' || true)"
    _declined_before=()
    [[ -n "$_declined_str" ]] && IFS=',' read -ra _declined_before <<< "$_declined_str"

    # ── Pull latest code ─────────────────────────────────────────────────────
    tmp_dir="$(mktemp -d)"
    git clone --depth 1 "$REPO_URL" "$tmp_dir"
    rsync -a --delete \
        --exclude='.env' \
        --exclude='.env.bak.*' \
        --exclude='.venv' \
        "$tmp_dir/" "${INSTALL_DIR}/"
    rm -rf "$tmp_dir"
    success "Code updated."

    cd "$INSTALL_DIR"

    # ── Discover optional tools available after the pull ─────────────────────
    # Required tools (required = True) are always kept and excluded from choices.
    _available_now=()
    for _f in tools/*.py; do
        [[ -f "$_f" ]] || continue
        _stem="$(basename "$_f" .py)"
        case "$_stem" in __init__|base|runner) continue ;; esac
        [[ "$(tool_required "$_f")" == "true" ]] && continue
        _available_now+=("$_stem")
    done

    # ── Identify genuinely new tools ─────────────────────────────────────────
    # A tool is "new" if it's in the pulled code but was neither installed
    # before nor explicitly declined — so we never re-ask about declined tools.
    _new_tools=()
    for _t in ${_available_now[@]+"${_available_now[@]}"}; do
        _known=0
        for _i in ${_installed_before[@]+"${_installed_before[@]}"}; do
            [[ "$_i" == "$_t" ]] && _known=1 && break
        done
        for _d in ${_declined_before[@]+"${_declined_before[@]}"}; do
            [[ "$_d" == "$_t" ]] && _known=1 && break
        done
        [[ $_known -eq 0 ]] && _new_tools+=("$_t")
    done

    # ── Ask about new tools ───────────────────────────────────────────────────
    _tools_to_keep=(${_installed_before[@]+"${_installed_before[@]}"})
    _declined_final=(${_declined_before[@]+"${_declined_before[@]}"})

    if [[ ${#_new_tools[@]} -gt 0 ]]; then
        echo
        echo -e "${BOLD}New tools available:${RESET}"
        for _t in "${_new_tools[@]}"; do
            _desc="$(tool_description "$_t")"
            read -rp "  Install ${_t} — ${_desc}? [Y/n]: " _yn
            case "${_yn:-Y}" in
                y|Y) _tools_to_keep+=("$_t") ;;
                *)   _declined_final+=("$_t") ;;
            esac
        done
    fi

    # ── Optional: reconfigure all tools (re-offer previously declined) ────────
    if [[ ${#_declined_before[@]} -gt 0 ]]; then
        echo
        read -rp "  Reconfigure all tools (review previously declined)? [y/N]: " _reconfig
        if [[ "${_reconfig:-N}" =~ ^[Yy]$ ]]; then
            _tools_to_keep=()
            _declined_final=()
            echo
            echo -e "${BOLD}All available tools (including previously declined):${RESET}"
            for _t in ${_available_now[@]+"${_available_now[@]}"}; do
                _desc="$(tool_description "$_t")"
                read -rp "  Install ${_t} — ${_desc}? [Y/n]: " _yn
                case "${_yn:-Y}" in
                    y|Y) _tools_to_keep+=("$_t") ;;
                    *)   _declined_final+=("$_t") ;;
                esac
            done
        fi
    fi

    # ── Prune tools not in the keep list (required tools are never pruned) ───
    for _f in tools/*.py; do
        [[ -f "$_f" ]] || continue
        _stem="$(basename "$_f" .py)"
        case "$_stem" in __init__|base|runner) continue ;; esac
        [[ "$(tool_required "$_f")" == "true" ]] && continue
        _keep=0
        for _t in ${_tools_to_keep[@]+"${_tools_to_keep[@]}"}; do
            [[ "$_t" == "$_stem" ]] && _keep=1 && break
        done
        if [[ $_keep -eq 0 ]]; then
            rm -f "tools/${_stem}.py"
            info "  removed tools/${_stem}.py"
        fi
    done

    # ── Persist updated tool state in .env ───────────────────────────────────
    if [[ -f "$ENV_FILE" ]]; then
        _inst_csv=""
        [[ ${#_tools_to_keep[@]} -gt 0 ]] && _inst_csv="$(join_comma "${_tools_to_keep[@]}")"
        _decl_csv=""
        [[ ${#_declined_final[@]} -gt 0 ]] && _decl_csv="$(join_comma "${_declined_final[@]}")"
        update_env_var "SETUP_INSTALLED_TOOLS" "$_inst_csv" "$ENV_FILE"
        update_env_var "SETUP_DECLINED_TOOLS"  "$_decl_csv" "$ENV_FILE"
    fi

    # ── Install dependencies for the current tool set ─────────────────────────
    info "Updating Python dependencies…"
    _upd_extras=()
    for _t in ${_tools_to_keep[@]+"${_tools_to_keep[@]}"}; do
        _ex="$(tool_extras "$_t")"
        [[ -n "$_ex" ]] && _upd_extras+=("$_ex")
    done
    if grep -q '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null; then
        _upd_extras+=(telegram)
    fi

    if [[ ${#_upd_extras[@]} -gt 0 ]]; then
        _extra_args=()
        for _e in "${_upd_extras[@]}"; do _extra_args+=(--extra "$_e"); done
        "$UV_BIN" sync "${_extra_args[@]}" || die "Dependency update failed."
    else
        "$UV_BIN" sync || die "Dependency update failed."
    fi
    success "Dependencies updated."

    echo
    echo -e "${GREEN}${BOLD}══════════════════════════════════════════════${RESET}"
    echo -e "${GREEN}${BOLD}  Pie-Brain updated successfully!${RESET}"
    echo -e "${GREEN}${BOLD}══════════════════════════════════════════════${RESET}"
    echo
    echo "  Your settings in ${INSTALL_DIR}/.env were preserved."
    if [[ ${#_new_tools[@]} -gt 0 ]]; then
        _new_csv="$(join_comma "${_new_tools[@]}")"
        echo "  New tools configured: ${_new_csv}"
    fi
    echo "  Restart the engine to apply changes."
    echo
    exit 0
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

# ─── Clone repository ─────────────────────────────────────────────────────────
# Cloned before tool selection so available tools can be discovered dynamically.
echo
info "Cloning repository into ${INSTALL_DIR}…"
tmp_dir="$(mktemp -d)"
git clone --depth 1 "$REPO_URL" "$tmp_dir"
rsync -a --delete "$tmp_dir/" "$INSTALL_DIR/"
rm -rf "$tmp_dir"
cd "$INSTALL_DIR"

# ─── Tool selection ───────────────────────────────────────────────────────────
# Discover optional tools from the cloned tools/ directory — no hardcoded list.
# Tools with required = True are always active and excluded from user-facing choices.
_all_optional_tools=()
for _f in tools/*.py; do
    [[ -f "$_f" ]] || continue
    _stem="$(basename "$_f" .py)"
    case "$_stem" in __init__|base|runner) continue ;; esac
    [[ "$(tool_required "$_f")" == "true" ]] && continue
    _all_optional_tools+=("$_stem")
done

echo
echo -e "${BOLD}Which tools should be installed?${RESET}"
echo "  Enter space-separated numbers, 'all', or 'none'."
echo "  Note: required tools (e.g. query) are always installed and not listed here."
echo
_idx=1
for _t in "${_all_optional_tools[@]}"; do
    printf "  %d) %-12s — %s\n" "$_idx" "$_t" "$(tool_description "$_t")"
    _idx=$(( _idx + 1 ))
done
echo
read -rp "  Choices [all]: " _tools_input
_tools_input="${_tools_input:-all}"

TOOLS=()
if [[ "$_tools_input" == "none" ]]; then
    :
elif [[ "$_tools_input" == "all" ]]; then
    TOOLS=("${_all_optional_tools[@]}")
else
    for _n in $_tools_input; do
        if [[ "$_n" =~ ^[0-9]+$ ]] && (( _n >= 1 && _n <= ${#_all_optional_tools[@]} )); then
            TOOLS+=("${_all_optional_tools[$(( _n - 1 ))]}")
        else
            warn "Unknown tool number '${_n}', skipping."
        fi
    done
fi
success "Tools: query (always) + ${TOOLS[*]:-none}"

# Compute which optional tools were declined — persisted so updates don't re-ask
_declined_fresh=()
for _t in "${_all_optional_tools[@]}"; do
    _sel=0
    for _s in ${TOOLS[@]+"${TOOLS[@]}"}; do
        [[ "$_s" == "$_t" ]] && _sel=1 && break
    done
    [[ $_sel -eq 0 ]] && _declined_fresh+=("$_t")
done

if [[ " ${TOOLS[*]} " == *" git_sync "* ]] && ! command -v gh &>/dev/null; then
    warn "'gh' CLI not found — required by git_sync. Install: https://cli.github.com"
fi

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

# Tools — remove any optional tool not selected by the user.
# Required tools (required = True) are always kept and cannot be disabled.
for _f in tools/*.py; do
    _stem="$(basename "$_f" .py)"
    case "$_stem" in __init__|base|runner) continue ;; esac
    [[ "$(tool_required "$_f")" == "true" ]] && continue
    _keep=0
    for _t in ${TOOLS[@]+"${TOOLS[@]}"}; do
        [[ "$_t" == "$_stem" ]] && _keep=1 && break
    done
    if [[ $_keep -eq 0 ]]; then
        rm -f "tools/${_stem}.py"
        info "  removed tools/${_stem}.py"
    fi
done

success "Repository trimmed to selected modules."

# ─── Build extras list & install dependencies ─────────────────────────────────
echo
info "Installing Python dependencies…"

EXTRAS=()
[[ "$PROVIDER" == "telegram" ]] && EXTRAS+=(telegram)
for _t in ${TOOLS[@]+"${TOOLS[@]}"}; do
    _ex="$(tool_extras "$_t")"
    [[ -n "$_ex" ]] && EXTRAS+=("$_ex")
done

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

read -rp "  Ollama router model [qwen3.5:2b]: " _ollama_model
OLLAMA_MODEL="${_ollama_model:-qwen3.5:2b}"

echo
echo -e "${BOLD}Dev mode (auto-pull updates):${RESET}"
echo "  When enabled, the engine watches the git remote and pulls new commits"
echo "  automatically, then restarts itself. Useful while actively developing;"
echo "  leave off for stable production installs."
read -rp "  Enable dev mode? [y/N]: " _dev_mode
DEV_MODE="false"
case "${_dev_mode:-N}" in
    y|Y) DEV_MODE="true" ; warn "Dev mode ON — engine will auto-pull and restart on new commits." ;;
    *)   success "Dev mode off (default)." ;;
esac

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
    if [[ -n "$TELEGRAM_ALLOWED" ]]; then
        _ids_json=$(python3 -c \
            "import json,sys; ids=sys.argv[1].split(','); print(json.dumps([int(i.strip()) for i in ids if i.strip()]))" \
            "$TELEGRAM_ALLOWED")
        echo "TELEGRAM_ALLOWED_USER_IDS=${_ids_json}"
    fi
    if [[ -n "$ARXIV_KEYWORDS" ]]; then
        # Convert "a, b, c" → JSON array for pydantic-settings
        _kw_json=$(python3 -c \
            "import json,sys; kw=sys.argv[1].split(','); print(json.dumps([k.strip() for k in kw]))" \
            "$ARXIV_KEYWORDS")
        echo "ARXIV_DISCOVER_KEYWORDS=${_kw_json}"
    fi
    # Tool state — used by the update branch to track new vs declined tools
    _inst_csv=""
    [[ ${#TOOLS[@]} -gt 0 ]] && _inst_csv="$(join_comma "${TOOLS[@]}")"
    echo "SETUP_INSTALLED_TOOLS=${_inst_csv}"
    _decl_csv=""
    [[ ${#_declined_fresh[@]} -gt 0 ]] && _decl_csv="$(join_comma "${_declined_fresh[@]}")"
    echo "SETUP_DECLINED_TOOLS=${_decl_csv}"
    # Dev mode
    echo "DEV_MODE=${DEV_MODE}"
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
# Type=notify: systemd waits for READY=1 from the engine before marking
# the service started, and kills/restarts if WATCHDOG=1 stops arriving.
Type=notify
WatchdogSec=120
WorkingDirectory=${INSTALL_DIR}
ExecStart=${UV_BIN} run --directory ${INSTALL_DIR} python -m core.engine
Restart=on-failure
RestartSec=10
# Allow up to 5 restarts per 5 minutes before systemd gives up.
StartLimitBurst=5
StartLimitIntervalSec=300
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

            systemctl --user daemon-reload
            systemctl --user enable pie-brain.service
            # Enable linger so the service starts at boot without an interactive login.
            loginctl enable-linger "$USER"
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
printf "  %-18s %s\n" "Tools:"          "query (always) + ${TOOLS[*]:-none}"
echo
echo -e "${BOLD}Next steps:${RESET}"
echo "  1. Pull your Ollama model:     ollama pull ${OLLAMA_MODEL}"[[ "$BRAIN" == "claude_code" ]] && \
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
