"""Constants for the Domolink-Mistral integration."""

DOMAIN = "domolink_mistral"

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
    "open-mistral-nemo",
    "mistral-small-latest",
]

SCAN_MODES = {
    MODE_LIVE: "Live (Analyse périodique)",
    MODE_BOOT: "Boot (3 min après démarrage)",
    MODE_MANUAL: "Manuel (Uniquement à la demande)"
}
