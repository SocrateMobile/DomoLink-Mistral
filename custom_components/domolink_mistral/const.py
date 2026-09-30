"""Constantes pour l'intégration Domolink-Mistral."""

DOMAIN = "domolink_mistral"
VERSION = "2.9.29"

CONF_API_KEY = "api_key"
CONF_MODEL = "model"
CONF_SCAN_MODE = "scan_mode"
CONF_SCAN_FREQUENCY = "scan_frequency"

MODE_LIVE = "live"
MODE_BOOT = "boot"
MODE_MANUAL = "manual"

DEFAULT_MODEL = "open-mistral-nemo"

MODELS = [
    "open-mistral-nemo",      # Recommandé (Gratuit / Rapide / 128k contexte)
    "ministral-8b-latest",    # Gratuit (Léger & Économe)
    "ministral-3b-latest",    # Gratuit (Ultra rapide)
    "codestral-latest",       # Gratuit (Spécialisé YAML & Code)
    "mistral-small-latest",   # Polyvalent
    "mistral-large-latest",   # Haute précision (Compte payant requis)
    "pixtral-12b-2409",       # Vision / Caméras
]

SCAN_MODES = {
    MODE_LIVE: "Live (Analyse périodique)",
    MODE_BOOT: "Boot (3 min après démarrage)",
    MODE_MANUAL: "Manuel (Uniquement à la demande)",
}

# Liste blanche des domaines autorisés pour l'auto-fix (appareils et helpers domestiques)
ALLOWED_FIX_DOMAINS = {
    "automation", "script", "input_boolean", "input_number",
    "input_select", "input_text", "input_datetime",
    "light", "switch", "cover", "fan", "climate", "media_player",
    "scene", "group", "timer", "counter", "number", "select",
    "button", "text", "date", "time", "notify",
}

# Services explicitement interdits (même si le domaine est autorisé)
BLOCKED_SERVICES = {
    "homeassistant.stop",
    "homeassistant.restart",
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
