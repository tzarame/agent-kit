#!/usr/bin/env bash
# install/keys.sh - the keys of setup.sh, read before any step of the set-up (install/setup.sh reads it with source,
# after common.sh): the set-up's own keys, and the start's keys as kit start reads them (kit/plan.py parse_start), so
# a wrong key is refused here with exit 2, before anything changes. tests/test_setup.py checks that the lists and the
# window's limit agree with kit/plan.py and kit/config.py

# the start's keys (kit/plan.py)
MODELS="opus sonnet haiku fable"
EFFORTS="low medium high xhigh max"
EDITOR="--code-server --vscode"
PARKED="--label --save --no-dashboard --clear -n --reset --role --addon --model --effort --sub-model --sub-effort --subagents --tools --env --env-clear --cli --centre"
ROLES_ADDONS="--qa --bare --design --development --toolsmith --fullstack --universal --gstack --playwright-cli --chrome-devtools-mcp --openspec --langfuse"
WINDOW_MAX=99999999                       # kit/config.py WINDOW_MAX
WORD='^[A-Za-z0-9._:/-]+$'                # kit/config.py WORD: a plugin's name
NAME='^[A-Za-z0-9_][A-Za-z0-9._-]*$'      # kit/config.py NAME: a project's name
# the set-up keys of the old kit, parked with their parts (--reset and --no-dashboard are in PARKED)
SETUP_PARKED="--install --here --dir --rc --nots --hq --no-autostart --no-code-server"

key_error() { echo "setup.sh: $*" >&2; exit 2; }
in_list() { case " $2 " in *" $1 "*) return 0 ;; esac; return 1; }

# window KEY VALUE: a number of tokens (132k or 132000) up to WINDOW_MAX, or default
window() {
  local n key=$1
  shift
  [ "$1" = default ] && return 0
  if [[ $1 =~ ^([1-9][0-9]{0,7})([kK]?)$ ]]; then
    n=${BASH_REMATCH[1]}; [ -z "${BASH_REMATCH[2]}" ] || n=$((n * 1000))
    [ "$n" -le "$WINDOW_MAX" ] && return 0
  fi
  key_error "$key $1: a number of tokens, like 132k or 132000, up to $WINDOW_MAX, or default"
}

# read_keys ARGS: sets PROJECT (the project, or owner/name with a link made owner/name; "" with none), START (0 with
# --no-start), NOUPD (1 with --no-update), DRY (1 with --dry-run), OLDPLUG (1 with --remove-old-plugins), HELP (1
# with --help or -h) and KEYS (the start's keys, for kit start, --dry-run with them). A wrong key exits 2 with a
# message that names it. A project's name is checked by kit start
read_keys() {
  PROJECT="" START=1 NOUPD=0 DRY=0 HELP=0 OLDPLUG=0 APPID="" APPKEY="" KEYS=()
  case "${1:-}" in
    status|stop|list|agent) key_error "$1: no longer a command of setup.sh: kit list shows the sessions, kit kill ID stops one" ;;
  esac
  local a
  while [ $# -gt 0 ]; do
    a=$1; shift
    case "$a" in
      --help|-h) HELP=1 ;;
      --no-start) START=0 ;;
      --no-update) NOUPD=1 ;;
      --remove-old-plugins) OLDPLUG=1 ;;
      --dry-run) DRY=1; KEYS+=("$a") ;;
      --new) KEYS+=("$a") ;;
      --eco | --profile) key_error "$a is gone; an agent in its place: --agent NAME" ;;
      --app-client-id)
        { [ $# -gt 0 ] && [[ $1 =~ ^[A-Za-z0-9.]+$ ]]; } \
          || key_error "--app-client-id needs the Client ID of your GitHub App"
        APPID=$1; shift ;;
      --app-key)
        { [ $# -gt 0 ] && [ -n "$1" ] && [ "${1#-}" = "$1" ]; } \
          || key_error "--app-key needs the file of the App's private key"
        APPKEY=$1; shift ;;
      --repo)
        { [ $# -gt 0 ] && [ -n "$1" ] && [ "${1#-}" = "$1" ]; } || key_error "--repo needs a repository: owner/name or a link"
        project "$(gh_name "$1")"; shift ;;
      --window | --compact)
        [ $# -gt 0 ] || key_error "$a needs a value: a number of tokens, like 132k or 132000, or default"
        window "$a" "$1"; KEYS+=("$a" "$1"); shift ;;
      --agent)
        { [ $# -gt 0 ] && [[ $1 =~ $WORD ]]; } || key_error "--agent needs an agent's name, like --agent qa"
        KEYS+=("$a" "$1"); shift ;;
      --plugin)
        { [ $# -gt 0 ] && [[ $1 =~ $WORD ]]; } || key_error "--plugin needs a plugin's name, like --plugin qa"
        KEYS+=("$a" "$1"); shift ;;
      --*) if in_list "${a#--}" "$MODELS" || in_list "${a#--}" "$EFFORTS"; then KEYS+=("$a")
           else refused "$a"; fi ;;
      -*) refused "$a" ;;
      *) project "$(gh_name "$a")" ;;
    esac
  done
  return 0
}

# refused KEY: a key that is not the set-up's or the start's, with what it was
refused() {
  if in_list "$1" "$EDITOR"; then key_error "$1: the editor is parked"
  elif in_list "$1" "$ROLES_ADDONS"; then key_error "$1: a role or an add-on of the old kit; an agent or a plugin now: --agent NAME, --plugin NAME"
  elif in_list "$1" "$PARKED"; then key_error "$1: the key of a parked part"
  elif in_list "$1" "$SETUP_PARKED"; then key_error "$1: a set-up key of a parked part"
  else key_error "unknown option $1"; fi
}

# project NAME: the one project of the run
project() {
  [ -z "$PROJECT" ] || key_error "one project only, not $PROJECT and $1"
  PROJECT=$1
}

usage() {
  cat <<'EOF'
usage: setup.sh [PROJECT | owner/name] [KEYS]   set the machine up, then start a session of the project
  PROJECT        a project of the config, or a folder in the projects' folder (AGENT_KIT_ROOT, else the home folder);
                 owner/name or a GitHub link: cloned there when its folder is missing. Left out: the set-up only
  --repo R       the same as giving R first
  --no-start     set up only: no session is started
  --no-update    the kit's copy is not moved to the latest release
  --app-client-id ID   advanced: the Client ID of your GitHub App, kept in ~/.config/agent-kit/app-client-id: the
                 sign-in is then a code for that App. With none the sign-in is your own, by gh auth login
  --app-key FILE advanced: the App's private key: checked against GitHub and copied to
                 ~/.config/agent-kit/app-key.pem, so the agent acts as the App itself
  --remove-old-plugins   remove the plugins and the marketplace agent-kit that the old kit installed in Claude
                 Code; a session of the old kit that still runs loses them
  --dry-run      change nothing: each step says what it would do, and kit start prints the session's plan
  --opus --sonnet --haiku --fable          the session's model, for this session only
  --low --medium --high --xhigh --max      the session's effort, for this session only
  --window N|default                       the context window, like 132k or 132000
  --compact N|default                      the size the session compacts at, in place of the context window
  --agent NAME                             the session's agent (its role): dev, dev-eco, design, qa, spec, toolsmith
  --plugin NAME                            one more plugin for this session
  --new                                    begin a new conversation, not the last one of the folder
The sessions: kit list, kit attach ID, kit kill ID; kit help says the rest.
EOF
}
