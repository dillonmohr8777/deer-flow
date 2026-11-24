#!/usr/bin/env python3
"""Monthly / on-demand Florida Health Finder CSV importer for Placement Desk.

Reads a Florida Health Finder or master community directory CSV, intentionally
ignores any public Google/Facebook review columns, and performs a non-destructive
upsert into the Placement Desk SQLite store (never overwriting owner ratings,
contract status, Monday vacancy pulses, custom rates, or owner-added homes).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vhin_placement.api import upsert_directory_batch
from vhin_placement.models import DirectorySyncItem, DirectorySyncRequest
from vhin_placement.store import Store

_BEDS_RE = re.compile(r"(\d+)\s+beds?", re.IGNORECASE)
_LIC_RE = re.compile(r"(ALF|AFCH|SNF|ADC|HCS)\s*#?\s*([A-Za-z0-9\-]+)", re.IGNORECASE)


def parse_directory_csv(csv_path: Path) -> list[DirectorySyncItem]:
    items: list[DirectorySyncItem] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("Name") or row.get("name") or "").strip()
            city = (row.get("City") or row.get("city") or "").strip()
            if not name or not city:
                continue
            category = (row.get("Category") or row.get("category") or "").strip() or None
            raw_miles = (row.get("Miles from office") or row.get("miles_from_office") or "").strip()
            miles = None
            if raw_miles:
                try:
                    miles = float(raw_miles)
                except ValueError:
                    miles = None
            raw_lic = (row.get("AHCA license") or row.get("ahca_license") or "").strip()
            beds = None
            if row.get("licensed_beds"):
                try:
                    beds = int(row["licensed_beds"])
                except ValueError:
                    beds = None
            elif raw_lic:
                m_beds = _BEDS_RE.search(raw_lic)
                if m_beds:
                    beds = int(m_beds.group(1))
            ahca_license = None
            if raw_lic:
                m_lic = _LIC_RE.search(raw_lic)
                ahca_license = f"{m_lic.group(1).upper()} #{m_lic.group(2)}" if m_lic else raw_lic[:120]
            phone = (row.get("Phone") or row.get("contact_phone") or "").strip() or None
            if phone and not 7 <= len("".join(filter(str.isdigit, phone))) <= 15:
                phone = None
            address = (row.get("Address") or row.get("address") or "").strip() or None
            website = (row.get("Website") or row.get("source_url") or "").strip() or None
            if website and not website.startswith(("http://", "https://")):
                website = None
            services = [category.lower()] if category else []
            items.append(
                DirectorySyncItem(
                    name=name,
                    city=city,
                    category=category,
                    licensed_beds=beds,
                    ahca_license=ahca_license,
                    address=address,
                    miles_from_office=miles,
                    contact_phone=phone,
                    source_url=website,
                    services=services,
                    care_levels=[category] if category else [],
                )
            )
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-destructive monthly Florida Health Finder upsert into Placement Desk.")
    parser.add_argument("csv_path", type=Path, help="Path to Florida Health Finder / directory CSV")
    parser.add_argument("--data-dir", type=Path, required=True, help="Placement Desk persistent data_dir")
    parser.add_argument("--org-id", required=True, help="Configured VHIN organization_id")
    parser.add_argument("--workspace-id", default="vhin-placement")
    parser.add_argument("--actor", default="monthly-ahca-sync")
    parser.add_argument("--source-label", default="florida_health_finder")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = parse_directory_csv(args.csv_path)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "parsed_items": len(items), "sample": items[0].model_dump(mode="json") if items else None}, indent=2))
        return 0
    if not items:
        print(json.dumps({"added": 0, "updated": 0, "total_processed": 0}))
        return 0
    req = DirectorySyncRequest(source_label=args.source_label, items=items)
    store = Store(args.data_dir, args.org_id, args.workspace_id, args.actor)
    with store.transaction() as connection:
        summary = upsert_directory_batch(connection, req, actor=args.actor)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
