import json
import os
import re
import subprocess
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

URL = "https://en.macromicro.me/series/2793/semiconductor-dram-stock-index"
JSON_FILE = "history.json"


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

    Stratégie (du plus fiable au plus dégradé) :
      1. Lire directement Highcharts.charts[0].series[0].data — c'est ce que
         la page utilise en interne, et c'est la valeur avec sa précision
         complète (ex: 9671.4083, pas l'affichage arrondi 9,671.41).
      2. Fallback sur le sélecteur CSS de la "stat header" affichée.
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

        # Bannière cookies éventuelle
        try:
            accept = page.locator("button:has-text('Accept')")
            if accept.count() > 0:
                accept.first.click(timeout=3000)
        except Exception:
            pass

        # Laisser Highcharts s'initialiser avec les données
        page.wait_for_function(
            "() => typeof Highcharts !== 'undefined' "
            "&& Highcharts.charts "
            "&& Highcharts.charts.some(c => c && c.series && c.series[0] "
            "&& c.series[0].data && c.series[0].data.length > 0)",
            timeout=60000,
        )

        # --- Source primaire : objet Highcharts (précision complète) ---
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

        # --- Fallback : sélecteur CSS de la valeur affichée ---
        if not last_point or last_point.get("y") is None:
            displayed = page.locator(
                ".mm-cc-chart-stats-title .stat-val .val"
            ).first.inner_text(timeout=10000)
            num = float(displayed.replace(",", "").strip())
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            browser.close()
            return date_str, num

        browser.close()

        # x est un timestamp ms UTC -> date YYYY-MM-DD
        ts_ms = last_point["x"]
        date_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        value = float(last_point["y"])
        return date_str, value


def update_history(date_str, value):
    history = load_history()
    for item in history:
        if item["time"] == date_str:
            item["value"] = value
            save_history(history)
            return
    history.append({"time": date_str, "value": value})
    history.sort(key=lambda x: x["time"])
    save_history(history)


def git_push(date_str, value):
    subprocess.run(["git", "add", "history.json"], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"update DRAM index {date_str} {value}"],
        check=False,
    )
    subprocess.run(["git", "push", "origin", "main"], check=True)


def main():
    date_str, value = fetch_value()
    print(f"Valeur collectée : {value}  (date publiée : {date_str})")
    update_history(date_str, value)
    git_push(date_str, value)


if __name__ == "__main__":
    main()
