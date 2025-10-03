#!/usr/bin/env python3
"""
List Canvas course content (read-only):
- Prints course name
- Shows module titles with items (and their URLs)
- Attempts to list files (will skip if 403)

Usage:
  export CANVAS_API_TOKEN="YOUR_TOKEN"
  python list_canvas_course_content.py --domain canvas.odu.edu --course-id 188076
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests


def normalize_domain(d: str) -> str:
    d = d.strip()
    if "://" in d:
        return urlparse(d).netloc
    return d.split("/")[0]


def get_all(session: requests.Session, url: str, params: Optional[dict] = None) -> List[dict]:
    """Fetch all pages for a Canvas collection endpoint using Link headers."""
    results: List[dict] = []
    while url:
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            raise requests.HTTPError("401 Unauthorized", response=resp)
        if resp.status_code == 403:
            raise requests.HTTPError("403 Forbidden", response=resp)
        if resp.status_code == 404:
            raise requests.HTTPError("404 Not Found", response=resp)
        resp.raise_for_status()

        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            items = data.get("items", [])
            if isinstance(items, list):
                results.extend(items)

        # parse RFC5988 Link header
        link = resp.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            segs = [s.strip() for s in part.split(";")]
            if len(segs) < 2:
                continue
            href = segs[0].strip("<> ")
            rel = None
            for attr in segs[1:]:
                if attr.startswith("rel="):
                    rel = attr.split("=", 1)[1].strip('"')
            if rel == "next":
                next_url = href
        url = next_url
        params = None  # subsequent pages already contain query in the next URL
    return results


def sizeof_fmt(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description="List modules and files for a Canvas course.")
    parser.add_argument("--domain", required=True, help="Canvas domain (e.g., canvas.odu.edu)")
    parser.add_argument("--course-id", required=True, type=int, help="Canvas course ID")
    parser.add_argument(
        "--token",
        help="Canvas API token (or set CANVAS_API_TOKEN)",
    )
    parser.add_argument("--limit-modules", type=int, default=25, help="Max modules to print (default 25)")
    args = parser.parse_args()

    token = args.token or os.environ.get("CANVAS_API_TOKEN")
    if not token:
        print("Error: provide --token or set CANVAS_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    domain = normalize_domain(args.domain)
    base = f"https://{domain}/api/v1"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    # 1) Course summary
    try:
        cr = session.get(f"{base}/courses/{args.course_id}", timeout=30)
        if cr.status_code == 401:
            print("Auth failed (401). Check token/permissions.", file=sys.stderr)
            sys.exit(3)
        if cr.status_code == 404:
            print("Course not found (404). Check course ID/enrollment.", file=sys.stderr)
            sys.exit(4)
        cr.raise_for_status()
    except requests.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(2)

    course = cr.json()
    cname = course.get("name", f"course_{args.course_id}")
    print(f"📚 Course: {cname} (id={course.get('id')})")
    print(f"    Code: {course.get('course_code')} | State: {course.get('workflow_state')}\n")

    # 2) Modules with items
    try:
        modules = get_all(session, f"{base}/courses/{args.course_id}/modules", params={"per_page": 100})
    except requests.RequestException as e:
        print(f"Could not fetch modules: {e}", file=sys.stderr)
        modules = []

    print("🔹 Modules (with items):")
    if not modules:
        print("    (none visible to your account)")
    else:
        for i, m in enumerate(modules[: args.limit_modules], start=1):
            print(f"\n    {i:2d}. {m.get('name')}  [items: {m.get('items_count', '?')}]")
            mid = m.get("id")
            try:
                items = get_all(
                    session,
                    f"{base}/courses/{args.course_id}/modules/{mid}/items",
                    params={"per_page": 100},
                )
            except requests.RequestException:
                items = []
            for it in items:
                title = it.get("title") or "(untitled)"
                ttype = it.get("type")
                url = it.get("html_url") or it.get("url") or ""
                print(f"        - {title} ({ttype}) {url}")
        if len(modules) > args.limit_modules:
            print(f"\n    … plus {len(modules) - args.limit_modules} more")

    print()

    # 3) Files grouped by folders (may be forbidden for student tokens)
    print("📂 Files by folder:")
    try:
        # folders
        folders = get_all(session, f"{base}/courses/{args.course_id}/folders", params={"per_page": 100})
        folder_map: Dict[int, str] = {}
        for f in folders:
            fid = int(f.get("id"))
            full = (f.get("full_name") or "").replace("\\", "/")
            prefix = "course files/"
            rel = full[len(prefix) :] if full.lower().startswith(prefix) else full
            rel = rel.strip("/") or "(Root)"
            folder_map[fid] = rel

        # files
        files = get_all(
            session,
            f"{base}/courses/{args.course_id}/files",
            params={"per_page": 100, "sort": "updated_at", "order": "desc"},
        )

        if not files:
            print("    (no files)")
        else:
            by_folder: Dict[str, List[dict]] = {}
            for f in files:
                folder_id = f.get("folder_id")
                folder_name = folder_map.get(int(folder_id), "(Unknown folder)") if folder_id else "(Root)"
                by_folder.setdefault(folder_name, []).append(f)

            for folder_name in sorted(by_folder.keys()):
                print(f"  • {folder_name}")
                for f in by_folder[folder_name]:
                    name = f.get("display_name") or f.get("filename") or f"file_{f.get('id')}"
                    size = sizeof_fmt(int(f.get("size") or 0))
                    updated = f.get("updated_at")
                    print(f"      - {name}  [{size}]  (updated {updated})")

    except requests.HTTPError as e:
        # Catch 403 here and continue (your case)
        if e.response is not None and e.response.status_code == 403:
            print("    (no files or API access to /files is forbidden for your token)")
        else:
            print(f"    Could not fetch files: {e}", file=sys.stderr)

    print("\n(End of listing — no files were downloaded.)")


if __name__ == "__main__":
    main()
