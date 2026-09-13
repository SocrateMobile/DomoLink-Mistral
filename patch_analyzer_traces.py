import re

with open("custom_components/domolink_mistral/analyzer.py", "r") as f:
    content = f.read()

trace_func = """
# ═══════════════════════════════════════════════════════
# SECTION X : Analyse des traces d'automatisation
# ═══════════════════════════════════════════════════════

async def _get_automation_traces(hass: HomeAssistant) -> str:
    \"\"\"Récupère les dernières traces d'automatisations en erreur.\"\"\"
    import json
    import os
    trace_file = hass.config.path(".storage", "trace.saved_traces")
    if not os.path.exists(trace_file):
        return ""
    try:
        def read_traces():
            with open(trace_file, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                if "data" in data and isinstance(data["data"], dict):
                    traces = []
                    for auto_id, run_list in data["data"].items():
                        for run in run_list:
                            # Ne prendre que les erreurs récentes si possible
                            traces.append(json.dumps(run))
                    return "\\n\\n".join(traces[-5:]) # Retourne les 5 plus récentes
            return ""
            
        traces_str = await hass.async_add_executor_job(read_traces)
        if traces_str:
            return traces_str
    except Exception as e:
        _LOGGER.debug("DomoLink-Mistral: Erreur lecture des traces d'automatisations: %s", e)
    return ""

"""

# Insert before "async def get_recent_logs"
content = content.replace("async def get_recent_logs(hass: HomeAssistant, lines: int = 200) -> str:", trace_func + "async def get_recent_logs(hass: HomeAssistant, lines: int = 200) -> str:")

# Now insert the call in get_recent_logs
call_traces = """
    # 9. Traces d'automatisations
    _LOGGER.info("DomoLink-Mistral: [9/9] Analyse des traces...")
    traces = await _get_automation_traces(hass)
    if traces:
        sections.append(f"=== TRACES D'AUTOMATISATIONS (Récentes) ===\\n{traces}")

    if not sections:
"""
content = content.replace("    if not sections:", call_traces)

# Also update the log message that says 1/8 to 1/9 etc
content = content.replace("[1/8]", "[1/9]").replace("[2/8]", "[2/9]").replace("[3/8]", "[3/9]").replace("[4/8]", "[4/9]").replace("[5/8]", "[5/9]").replace("[6/8]", "[6/9]").replace("[7/8]", "[7/9]").replace("[8/8]", "[8/9]")

with open("custom_components/domolink_mistral/analyzer.py", "w") as f:
    f.write(content)
