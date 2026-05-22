import json
import os
import re
import subprocess
from datetime import datetime

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



def extract_latest_value(page_text):
    matches = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", page_text)

    numbers = []

    for match in matches:
        try:
            value = float(match.replace(",", ""))
            numbers.append(value)
        except:
            pass

    if not numbers:
        raise Exception("Aucune valeur détectée")

    filtered = [n for n in numbers if 100 < n < 100000]

    if not filtered:
        raise Exception("Aucune valeur cohérente trouvée")

    return filtered[0]



def fetch_value():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
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
        except:
            pass

        page.wait_for_timeout(5000)

        body_text = page.locator("body").inner_text()

        browser.close()

        return extract_latest_value(body_text)



def update_history(value):
    today = datetime.utcnow().strftime("%Y-%m-%d")

    history = load_history()

    for item in history:
        if item["time"] == today:
            item["value"] = value
            save_history(history)
            return

    history.append({
        "time": today,
        "value": value,
    })

    history.sort(key=lambda x: x["time"])

    save_history(history)



def git_push(value):
    subprocess.run(["git", "add", "history.json"], check=True)

    subprocess.run(
        ["git", "commit", "-m", f"update DRAM index {value}"],
        check=False,
    )

    subprocess.run(["git", "push", "origin", "main"], check=True)



def main():
    value = fetch_value()

    print(f"Valeur collectée : {value}")

    update_history(value)

    git_push(value)


if __name__ == "__main__":
    main()
