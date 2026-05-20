#!/usr/bin/env python3
"""
Finds your LinkedIn organization/company page ID by vanity name.

Usage:
  python linkedin_list_orgs.py
  python linkedin_list_orgs.py prophecytechs
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip()
if not token:
    print("[ERROR] LINKEDIN_ACCESS_TOKEN not set in .env")
    raise SystemExit(1)

headers = {
    "Authorization": f"Bearer {token}",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": "202401",
}

# ── Get vanity name ───────────────────────────────────────────────────────────

if len(sys.argv) > 1:
    vanity = sys.argv[1].strip().lstrip("@")
else:
    print("\nEnter your company LinkedIn URL slug.")
    print("Example: if your page is  linkedin.com/company/prophecytechs/")
    print("         enter:           prophecytechs\n")
    vanity = input("Company URL slug: ").strip().lstrip("@")

if not vanity:
    print("[ERROR] No vanity name provided.")
    raise SystemExit(1)

# ── Look up by vanity name ────────────────────────────────────────────────────

print(f"\nLooking up organization: {vanity} ...")

resp = requests.get(
    "https://api.linkedin.com/v2/organizations",
    params={"q": "vanityName", "vanityName": vanity},
    headers=headers,
    timeout=15,
)

if not resp.ok:
    # Fallback: try the older /v2/companies endpoint
    resp2 = requests.get(
        "https://api.linkedin.com/v2/companies",
        params={"q": "vanityName", "vanityName": vanity},
        headers=headers,
        timeout=15,
    )
    if resp2.ok:
        resp = resp2
    else:
        print(f"\n[ERROR] Could not look up organization ({resp.status_code}):")
        print(resp.text)
        print("\nManual alternative:")
        print("  1. Open your LinkedIn company page in a browser while logged in")
        print("  2. Click 'Admin tools' (top right of the page)")
        print("  3. The URL will contain the numeric ID, e.g.:")
        print("     linkedin.com/company/12345678/admin/")
        print("  4. Use that number as LINKEDIN_ORG_ID in .env")
        raise SystemExit(1)

elements = resp.json().get("elements", [])
if not elements:
    print(f"[ERROR] No organization found with vanity name '{vanity}'.")
    print("Check the spelling — it should match exactly the slug in the LinkedIn URL.")
    raise SystemExit(1)

org      = elements[0]
org_urn  = org.get("id", "") or org.get("$URN", "")
# id field may already be the full URN or just the numeric part
org_id   = org_urn.split(":")[-1] if ":" in str(org_urn) else str(org_urn)
org_name = org.get("localizedName") or org.get("name", {}).get("localized", {})

print(f"\n  Name : {org_name}")
print(f"  URN  : urn:li:organization:{org_id}")
print(f"  ID   : {org_id}")
print(f"\nAdd to .env:")
print(f"  LINKEDIN_ORG_ID={org_id}")
