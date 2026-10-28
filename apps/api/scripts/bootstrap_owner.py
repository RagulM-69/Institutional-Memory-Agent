"""
Owner Bootstrap Script for Institutional Memory Agent.

Safely provisions the initial owner account, organization, and admin membership
using administrative credentials (SUPABASE_SERVICE_ROLE_KEY).

This script never weakens RLS policies, never exposes service-role keys to the frontend,
and allows the project owner to bootstrap their workspace cleanly.

Usage:
    python -m apps.api.scripts.bootstrap_owner --email owner@example.com --org-name "Acme Corp" --org-slug "acme-corp"
    (You will be prompted securely for a password or supply via --password)
"""

import argparse
import asyncio
import getpass
import secrets
import sys
import uuid
from typing import Any

import httpx

from apps.api.config import Settings


async def bootstrap_owner(
    email: str,
    password: str,
    org_name: str,
    org_slug: str,
) -> dict[str, Any]:
    settings = Settings()

    supabase_url = settings.supabase_url.rstrip("/")
    if not supabase_url:
        raise ValueError("SUPABASE_URL is not set in environment or .env file.")

    service_key = settings.supabase_service_role_key.get_secret_value()
    if not service_key:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is not set in environment or .env file.")

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        # ─────────────────────────────────────────────────────────────
        # 1. Check or create the user in Supabase Auth via Admin API
        # ─────────────────────────────────────────────────────────────
        user_id: str | None = None

        # Search existing users
        users_resp = await client.get(
            f"{supabase_url}/auth/v1/admin/users",
            headers=headers,
            params={"page": 1, "per_page": 50},
        )
        if users_resp.status_code == 200:
            existing_users = users_resp.json().get("users", [])
            for u in existing_users:
                if u.get("email", "").lower() == email.lower():
                    user_id = u.get("id")
                    break

        if user_id:
            print(f"[*] Found existing auth user: {email} (id: {user_id})")
        else:
            print(f"[*] Creating new auth user: {email}...")
            create_user_resp = await client.post(
                f"{supabase_url}/auth/v1/admin/users",
                headers=headers,
                json={
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                },
            )
            if create_user_resp.status_code not in (200, 201):
                # If error is user already exists, inspect
                error_body = create_user_resp.text
                raise RuntimeError(
                    f"Failed to create Supabase user (HTTP {create_user_resp.status_code}): {error_body}"
                )
            user_data = create_user_resp.json()
            user_id = user_data.get("id")
            if not user_id:
                raise RuntimeError(f"User created but no ID returned: {user_data}")
            print(f"[+] Auth user created successfully (id: {user_id})")

        # ─────────────────────────────────────────────────────────────
        # 2. Check or create the Organization in public.organizations
        # ─────────────────────────────────────────────────────────────
        org_resp = await client.get(
            f"{supabase_url}/rest/v1/organizations",
            headers=headers,
            params={"slug": f"eq.{org_slug}", "select": "id,name,slug"},
        )
        if org_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to query organizations (HTTP {org_resp.status_code}): {org_resp.text}"
            )

        existing_orgs = org_resp.json()
        org_id: str | None = None

        if existing_orgs:
            org_id = existing_orgs[0]["id"]
            print(f"[*] Found existing organization: '{existing_orgs[0]['name']}' (slug: {org_slug}, id: {org_id})")
        else:
            print(f"[*] Creating organization: '{org_name}' (slug: {org_slug})...")
            new_org_id = str(uuid.uuid4())
            create_org_resp = await client.post(
                f"{supabase_url}/rest/v1/organizations",
                headers={**headers, "Prefer": "return=representation"},
                json={
                    "id": new_org_id,
                    "name": org_name,
                    "slug": org_slug,
                },
            )
            if create_org_resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"Failed to create organization (HTTP {create_org_resp.status_code}): {create_org_resp.text}"
                )
            created_org = create_org_resp.json()
            if isinstance(created_org, list) and created_org:
                org_id = created_org[0]["id"]
            else:
                org_id = new_org_id
            print(f"[+] Organization created successfully (id: {org_id})")

        # ─────────────────────────────────────────────────────────────
        # 3. Check or create membership in public.memberships
        # ─────────────────────────────────────────────────────────────
        mem_resp = await client.get(
            f"{supabase_url}/rest/v1/memberships",
            headers=headers,
            params={"org_id": f"eq.{org_id}", "user_id": f"eq.{user_id}", "select": "id,role"},
        )
        if mem_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to query memberships (HTTP {mem_resp.status_code}): {mem_resp.text}"
            )

        existing_mems = mem_resp.json()
        if existing_mems:
            current_role = existing_mems[0]["role"]
            print(f"[*] Membership exists with role '{current_role}'")
            if current_role != "admin":
                print("[*] Updating membership role to 'admin'...")
                mem_id = existing_mems[0]["id"]
                patch_resp = await client.patch(
                    f"{supabase_url}/rest/v1/memberships?id=eq.{mem_id}",
                    headers=headers,
                    json={"role": "admin"},
                )
                if patch_resp.status_code not in (200, 204):
                    raise RuntimeError(f"Failed to update membership: {patch_resp.text}")
                print("[+] Membership updated to 'admin'")
        else:
            print("[*] Creating admin membership...")
            create_mem_resp = await client.post(
                f"{supabase_url}/rest/v1/memberships",
                headers={**headers, "Prefer": "return=representation"},
                json={
                    "org_id": org_id,
                    "user_id": user_id,
                    "role": "admin",
                },
            )
            if create_mem_resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"Failed to create membership (HTTP {create_mem_resp.status_code}): {create_mem_resp.text}"
                )
            print("[+] Admin membership created successfully")

    return {
        "user_id": user_id,
        "email": email,
        "org_id": org_id,
        "org_name": org_name,
        "org_slug": org_slug,
        "role": "admin",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap owner account and initial organization for Institutional Memory Agent."
    )
    parser.add_argument(
        "--email",
        type=str,
        default="owner@institutional-memory.local",
        help="Email address for the owner account (default: owner@institutional-memory.local)",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="Password for the owner account (if omitted, you will be prompted securely or a safe random password is generated)",
    )
    parser.add_argument(
        "--org-name",
        type=str,
        default="Acme Engineering",
        help="Display name for the organization (default: Acme Engineering)",
    )
    parser.add_argument(
        "--org-slug",
        type=str,
        default="acme-engineering",
        help="Unique URL-safe slug for the organization (default: acme-engineering)",
    )

    args = parser.parse_args()

    password = args.password
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Enter secure password for owner account (min 12 chars): ")
        else:
            # Non-interactive generation
            password = secrets.token_urlsafe(18)
            print("[!] Secure random password generated for owner account.", file=sys.stderr)
            print(f"[!] Ephemeral Password: {password}", file=sys.stderr)
            print("[!] Save this password immediately. It will not be shown again.", file=sys.stderr)

    if not password or len(password) < 12:
        print("[-] Error: Password must be at least 12 characters long.", file=sys.stderr)
        sys.exit(1)

    print("============================================================")
    print(" Institutional Memory Agent — Owner Bootstrap Tool")
    print("============================================================")

    try:
        result = asyncio.run(
            bootstrap_owner(
                email=args.email.strip(),
                password=password,
                org_name=args.org_name.strip(),
                org_slug=args.org_slug.strip().lower(),
            )
        )
    except Exception as e:
        print(f"[-] Bootstrap failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("------------------------------------------------------------")
    print(" Bootstrap completed successfully!")
    print(f" Organization : {result['org_name']} (slug: {result['org_slug']})")
    print(f" Org ID       : {result['org_id']}")
    print(f" Owner Email  : {result['email']}")
    print(f" User ID      : {result['user_id']}")
    print(f" Role         : {result['role']}")
    print("------------------------------------------------------------")
    print("You can now sign in at http://localhost:3000 using:")
    print(f"  Email    : {result['email']}")
    print("  Password : [configured password]")
    print("============================================================")


if __name__ == "__main__":
    main()

