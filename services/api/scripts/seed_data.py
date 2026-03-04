#!/usr/bin/env python3
"""Generate sample data for the Jonas Data Platform demo.

Produces:
  - 50 e-commerce orders (nested JSON with line_items)
  - 500 IoT sensor readings (CSV with some invalid values)
  - 100 CRM contacts (variable fields, PII-bearing)
"""

import csv
import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

OUTPUT_DIR = Path(__file__).parent.parent / "sample_data"
OUTPUT_DIR.mkdir(exist_ok=True)


def _dt(days_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


# --------------------------------------------------------------------------- #
# E-commerce orders                                                             #
# --------------------------------------------------------------------------- #

PRODUCTS = [
    ("prod-001", "Wireless Headphones", 79.99),
    ("prod-002", "USB-C Hub", 34.99),
    ("prod-003", "Mechanical Keyboard", 129.99),
    ("prod-004", "Monitor Stand", 49.99),
    ("prod-005", "Webcam HD", 89.99),
    ("prod-006", "Desk Lamp", 29.99),
    ("prod-007", "Mouse Pad XL", 19.99),
    ("prod-008", "Cable Management Kit", 14.99),
]

STATUSES = ["pending", "processing", "shipped", "delivered", "cancelled"]

COUNTRIES = ["US", "CA", "GB", "DE", "FR", "AU", "NL", "SE"]


def generate_orders(n: int = 50) -> list[dict]:
    orders = []
    for i in range(n):
        num_items = random.randint(1, 4)
        items = random.sample(PRODUCTS, min(num_items, len(PRODUCTS)))
        line_items = [
            {
                "product_id": p[0],
                "name": p[1],
                "unit_price": p[2],
                "qty": random.randint(1, 3),
                "subtotal": round(p[2] * random.randint(1, 3), 2),
            }
            for p in items
        ]
        total = sum(li["subtotal"] for li in line_items)
        orders.append(
            {
                "order_id": str(uuid.uuid4()),
                "customer_id": f"cust-{random.randint(1000, 9999)}",
                "status": random.choice(STATUSES),
                "created_at": _dt(days_ago=random.uniform(0, 90)),
                "shipping_country": random.choice(COUNTRIES),
                "currency": "USD",
                "subtotal": round(total, 2),
                "tax": round(total * 0.1, 2),
                "total": round(total * 1.1, 2),
                "line_items": line_items,
            }
        )
    return orders


# --------------------------------------------------------------------------- #
# IoT sensor readings                                                           #
# --------------------------------------------------------------------------- #

SENSOR_TYPES = ["temperature", "humidity", "pressure", "co2"]
DEVICE_IDS = [f"device-{i:03d}" for i in range(1, 21)]


def _maybe_invalid(value: float, pct: float = 0.04) -> str:
    if random.random() < pct:
        return random.choice(["N/A", "ERR", "", "null", "999999"])
    return str(round(value, 2))


def generate_sensor_readings(n: int = 500) -> list[dict]:
    rows = []
    for _ in range(n):
        sensor_type = random.choice(SENSOR_TYPES)
        if sensor_type == "temperature":
            value = random.gauss(22, 5)
        elif sensor_type == "humidity":
            value = random.uniform(30, 80)
        elif sensor_type == "pressure":
            value = random.gauss(1013, 10)
        else:  # co2
            value = random.gauss(400, 100)
        rows.append(
            {
                "reading_id": str(uuid.uuid4()),
                "device_id": random.choice(DEVICE_IDS),
                "sensor_type": sensor_type,
                "value": _maybe_invalid(value),
                "unit": {
                    "temperature": "°C",
                    "humidity": "%",
                    "pressure": "hPa",
                    "co2": "ppm",
                }[sensor_type],
                "recorded_at": _dt(days_ago=random.uniform(0, 30)),
                "location": f"zone-{random.randint(1, 5)}",
                "firmware_version": f"1.{random.randint(0, 5)}.{random.randint(0, 9)}",
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# CRM contacts                                                                  #
# --------------------------------------------------------------------------- #

FIRST_NAMES = [
    "Alice",
    "Bob",
    "Carol",
    "Dave",
    "Eve",
    "Frank",
    "Grace",
    "Hank",
    "Iris",
    "Jack",
    "Karen",
    "Liam",
    "Mia",
    "Noah",
    "Olivia",
    "Paul",
]
LAST_NAMES = [
    "Smith",
    "Jones",
    "Williams",
    "Brown",
    "Davis",
    "Miller",
    "Wilson",
    "Moore",
    "Taylor",
    "Anderson",
    "Thomas",
    "Jackson",
    "White",
    "Harris",
]
DOMAINS = ["example.com", "acme.io", "corp.net", "biz.org"]
COMPANIES = [
    "Acme Corp",
    "Globex",
    "Initech",
    "Umbrella",
    "Waystar",
    "Sterling Cooper",
    "Dunder Mifflin",
    "Bluth Company",
]
SEGMENTS = ["enterprise", "mid-market", "smb", "startup"]


def generate_contacts(n: int = 100) -> list[dict]:
    contacts = []
    for _ in range(n):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        domain = random.choice(DOMAINS)
        contact: dict = {
            "contact_id": str(uuid.uuid4()),
            "first_name": first,
            "last_name": last,
            "email": f"{first.lower()}.{last.lower()}@{domain}",
            "company": random.choice(COMPANIES),
            "segment": random.choice(SEGMENTS),
            "created_at": _dt(days_ago=random.uniform(0, 365)),
        }
        # Variable optional fields (30% chance each)
        if random.random() > 0.7:
            contact[
                "phone"
            ] = f"+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        if random.random() > 0.7:
            contact[
                "linkedin_url"
            ] = f"https://linkedin.com/in/{first.lower()}-{last.lower()}"
        if random.random() > 0.5:
            contact["notes"] = f"Met at conference {random.randint(2022, 2025)}"
        contacts.append(contact)
    return contacts


# --------------------------------------------------------------------------- #
# Main                                                                          #
# --------------------------------------------------------------------------- #


def main() -> None:
    # Orders → JSON
    orders = generate_orders(50)
    order_path = OUTPUT_DIR / "orders.json"
    order_path.write_text(json.dumps(orders, indent=2))
    print(f"[seed] {len(orders)} orders → {order_path}")

    # Sensor readings → CSV
    readings = generate_sensor_readings(500)
    sensor_path = OUTPUT_DIR / "sensor_readings.csv"
    with sensor_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=readings[0].keys())
        writer.writeheader()
        writer.writerows(readings)
    print(f"[seed] {len(readings)} sensor readings → {sensor_path}")

    # Contacts → JSON (variable fields)
    contacts = generate_contacts(100)
    contact_path = OUTPUT_DIR / "contacts.json"
    contact_path.write_text(json.dumps(contacts, indent=2))
    print(f"[seed] {len(contacts)} contacts → {contact_path}")


if __name__ == "__main__":
    sys.exit(main())
