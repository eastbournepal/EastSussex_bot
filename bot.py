import os
import re
import time
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

BOOKING_URL = "https://www.bookin1.com/bookingEngine/hotel/EASTUK/search/list"

ROOM_TYPES = [
    "Classic Double Room",
    "Classic Twin Room",
    "Club Double Room",
    "Club Twin Room",
    "Family Room",
    "Luxury Suite",
]


def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=30)


def short_room_name(name: str) -> str:
    for room in ROOM_TYPES:
        if room.lower() in name.lower():
            return room
    return name.strip()


def extract_room_prices(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    room_prices = []

    for i, line in enumerate(lines):
        matched_room = None
        for room in ROOM_TYPES:
            if room.lower() in line.lower():
                matched_room = room
                break

        if not matched_room:
            continue

        prices_found = []
        for j in range(1, 8):
            if i + j >= len(lines):
                break

            next_line = lines[i + j]

            if "save" in next_line.lower():
                continue

            for m in re.findall(r"£\s?(\d+(?:\.\d{2})?)", next_line):
                value = int(float(m))
                if value > 10:
                    prices_found.append(value)

        if prices_found:
            room_prices.append((matched_room, min(prices_found)))

    deduped = []
    seen = set()
    for item in room_prices:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return deduped


def open_calendar(page):
    page.get_by_role("textbox", name="Check-in").click()


def click_date_if_available(page, target_date):
    label = target_date.strftime("%A, %B ") + str(target_date.day) + ","

    btn = page.get_by_role("button", name=label)

    if btn.count() == 0:
        page.get_by_role("button", name=re.compile("Move forward")).click()
        page.wait_for_timeout(500)
        btn = page.get_by_role("button", name=label)

    aria = btn.get_attribute("aria-label") or ""
    if "Not available" in aria:
        return False

    btn.click()
    return True


def search_one_date(page, target_date):
    date_iso = target_date.strftime("%a %d %b")
    print("Checking:", date_iso)

    page.goto(BOOKING_URL, timeout=90000)
    page.wait_for_timeout(2500)

    open_calendar(page)

    available = click_date_if_available(page, target_date)
    if not available:
        print("DATE UNAVAILABLE")
        return {
            "date": date_iso,
            "cheapest_price": None,
            "cheapest_name": "Unavailable",
        }

    page.get_by_role("button", name=re.compile("Search")).click()
    page.wait_for_timeout(7000)

    text = page.locator("body").inner_text()
    room_prices = extract_room_prices(text)

    print("ROOM PRICES:", room_prices)

    if not room_prices:
        return {
            "date": date_iso,
            "cheapest_price": None,
            "cheapest_name": "N/A",
        }

    cheapest_name, cheapest_price = min(room_prices, key=lambda x: x[1])

    return {
        "date": date_iso,
        "cheapest_price": cheapest_price,
        "cheapest_name": short_room_name(cheapest_name),
    }


def check_prices_next_days(days=20):
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for i in range(1, days + 1):
            target_date = datetime.today() + timedelta(days=i)

            try:
                result = search_one_date(page, target_date)
                results.append(result)
            except Exception as e:
                print("ERROR:", target_date.strftime("%a %d %b"), e)
                results.append(
                    {
                        "date": target_date.strftime("%a %d %b"),
                        "cheapest_price": None,
                        "cheapest_name": "ERROR",
                    }
                )

        context.close()
        browser.close()

    valid = [r for r in results if r["cheapest_price"] is not None]
    best = min(valid, key=lambda x: x["cheapest_price"]) if valid else None

    return results, best


def job():
    results, best = check_prices_next_days(days=20)

    if best:
        lines = [
            "🏨 East Sussex National",
            "Next 20 days scan",
            "",
            "Cheapest available:",
            f"{best['date']} — £{best['cheapest_price']} ({best['cheapest_name']})",
            "",
            "All checked dates:",
        ]

        for r in results:
            if r["cheapest_price"] is None:
                lines.append(f"{r['date']} — {r['cheapest_name']}")
            else:
                lines.append(f"{r['date']} — £{r['cheapest_price']} ({r['cheapest_name']})")

        lines += ["", BOOKING_URL]
        msg = "\n".join(lines)
    else:
        msg = (
            "🏨 East Sussex National\n"
            "Next 20 days scan\n\n"
            "No prices found\n\n"
            f"{BOOKING_URL}"
        )

    print(msg)
    send(msg)


if __name__ == "__main__":
    job()  
