"""Constantes pour l'intégration Domolink-Mistral."""

DOMAIN = "domolink_mistral"
VERSION = "2.9.1"

CONF_API_KEY = "api_key"
CONF_MODEL = "model"
CONF_SCAN_MODE = "scan_mode"
CONF_SCAN_FREQUENCY = "scan_frequency"

MODE_LIVE = "live"
MODE_BOOT = "boot"
MODE_MANUAL = "manual"

DEFAULT_MODEL = "mistral-large-latest"

MODELS = [
    "mistral-large-latest",
    "mistral-small-latest",
    "open-mistral-nemo",
]

SCAN_MODES = {
    MODE_LIVE: "Live (Analyse périodique)",
    MODE_BOOT: "Boot (3 min après démarrage)",
    MODE_MANUAL: "Manuel (Uniquement à la demande)",
}

# Liste blanche des domaines autorisés pour l'auto-fix
ALLOWED_FIX_DOMAINS = {
    "automation", "script", "input_boolean", "input_number",
    "input_select", "input_text", "input_datetime",
    "light", "switch", "cover", "fan", "climate", "media_player",
    "scene", "group", "timer", "counter", "number", "select",
    "button", "text", "date", "time", "notify", "homeassistant",
}

# Services explicitement interdits (même si le domaine est autorisé)
BLOCKED_SERVICES = {
    "homeassistant.restart",
    "homeassistant.stop",
    "hassio.host_shutdown",
    "hassio.host_reboot",
    "hassio.addon_stop",
}

# Fichiers YAML autorisés pour la modification automatique
ALLOWED_YAML_FILES = {
    "configuration.yaml",
    "automations.yaml",
    "automation.yaml",
    "scripts.yaml",
    "script.yaml",
    "scenes.yaml",
    "scene.yaml",
}

STORAGE_KEY = "domolink_mistral.ignored_issues"
STORAGE_VERSION = 1
