import json
import logging
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

# --- Chemins absolus : le script est portable, fonctionne depuis n'importe quel cwd ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(SCRIPT_DIR, "history.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "collector.log")

URL = "https://en.macromicro.me/series/2793/semiconductor-dram-stock-index"

# --- Logger qui écrit dans un fichier ET sur stdout/stderr ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("collector")


def load_history():
    if not os.path.exists(JSON_FILE):
        return []
    with open(JSON_FILE, "r") as f:
        return json.load(f)


def save_history(data):
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=2)


def fetch_value():
    """
    Récupère le dernier point (date, valeur) du graphique DRAM Stock Index.

    Stratégie :
      1. Lire Highcharts.charts[0].series[0].data — précision complète.
      2. Fallback : sélecteur CSS .mm-cc-chart-stats-title .stat-val .val.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(URL, wait_until="networkidle", timeout=120000)

        try:
            accept = page.locator("button:has-text('Accept')")
            if accept.count() > 0:
                accept.first.click(timeout=3000)
        except Exception:
            pass

        page.wait_for_function(
            "() => typeof Highcharts !== 'undefined' "
            "&& Highcharts.charts "
            "&& Highcharts.charts.some(c => c && c.series && c.series[0] "
            "&& c.series[0].data && c.series[0].data.length > 0)",
            timeout=60000,
        )

        last_point = page.evaluate(
            """() => {
                const charts = (Highcharts.charts || []).filter(c => c);
                for (const c of charts) {
                    const s = c.series && c.series[0];
                    if (s && s.data && s.data.length) {
                        const p = s.data[s.data.length - 1];
                        return { x: p.x, y: p.y };
                    }
                }
                return null;
            }"""
        )

        if not last_point or last_point.get("y") is None:
            displayed = page.locator(
                ".mm-cc-chart-stats-title .stat-val .val"
            ).first.inner_text(timeout=10000)
            num = float(displayed.replace(",", "").strip())
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            browser.close()
            return date_str, num

        browser.close()

        ts_ms = last_point["x"]
        date_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        value = float(last_point["y"])
        return date_str, value


def update_history(date_str, value):
    history = load_history()
    for item in history:
        if item["time"] == date_str:
            if item["value"] == value:
                log.info("Valeur déjà à jour pour %s = %s, rien à faire.", date_str, value)
                return False
            item["value"] = value
            save_history(history)
            log.info("Valeur du %s mise à jour : %s", date_str, value)
            return True
    history.append({"time": date_str, "value": value})
    history.sort(key=lambda x: x["time"])
    save_history(history)
    log.info("Nouvelle entrée ajoutée : %s = %s", date_str, value)
    return True


def git_push(date_str, value):
    """git add/commit/push, toujours dans le bon dossier grâce à `-C SCRIPT_DIR`."""
    def run(args):
        log.info("$ %s", " ".join(args))
        result = subprocess.run(args, capture_output=True, text=True)
        if result.stdout:
            log.info("stdout: %s", result.stdout.strip())
        if result.stderr:
            log.info("stderr: %s", result.stderr.strip())
        return result.returncode

    run(["git", "-C", SCRIPT_DIR, "add", "history.json"])
    rc = run(["git", "-C", SCRIPT_DIR, "commit", "-m", f"update DRAM index {date_str} {value}"])
    if rc != 0:
        log.info("Rien à commiter (ou échec de commit) — on n'essaie pas de push.")
        return
    rc = run(["git", "-C", SCRIPT_DIR, "push", "origin", "main"])
    if rc != 0:
        log.error("Le push a échoué. Vérifier l'authentification git (clé SSH / token).")


def main():
    log.info("=== Démarrage collector (PID=%s, cwd=%s, script_dir=%s) ===",
             os.getpid(), os.getcwd(), SCRIPT_DIR)
    try:
        date_str, value = fetch_value()
        log.info("Valeur collectée : %s (date publiée : %s)", value, date_str)
        changed = update_history(date_str, value)
        if changed:
            git_push(date_str, value)
        log.info("=== Fin OK ===")
    except Exception:
        log.error("Erreur fatale :\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
