#!/usr/bin/env python3
"""
Download ALL files from a selected Canvas module by number.
Works even when /files is forbidden by:
- Downloading File items directly
- Fetching Page items and scraping linked file IDs
- Pulling Assignment attachments

Saves to: ~/Documents/<Course Name>/<CHOICE>/

Usage:
  export CANVAS_API_TOKEN="YOUR_TOKEN"
  python download_module_files.py --domain canvas.odu.edu --course-id 188076
  # or non-interactive:
  # python download_module_files.py --domain canvas.odu.edu --course-id 188076 --choice 8
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter, Retry
from tqdm import tqdm


# ----------------- Utilities -----------------

def normalize_domain(d: str) -> str:
    d = d.strip()
    if "://" in d:
        return urlparse(d).netloc
    return d.split("/")[0]


def build_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    retries = Retry(
        total=5,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET", "HEAD"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def get_all(session: requests.Session, url: str, params: Optional[dict] = None) -> List[dict]:
    """Fetch all pages for a Canvas collection endpoint using Link headers."""
    results: List[dict] = []
    while url:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            items = data.get("items", [])
            if isinstance(items, list):
                results.extend(items)
        # pagination
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
        params = None
    return results


_illegal = r'[<>:"/\\|?*\x00-\x1F]'
def sanitize(name: str) -> str:
    return re.sub(_illegal, "_", name).strip(" .")


def find_file_ids_in_html(html: str) -> Set[int]:
    """
    Find Canvas file IDs inside Page HTML. Handles both:
      - /files/123456/download ... (links in page body)
      - data-api-endpoint=".../api/v1/files/123456"
    """
    ids: Set[int] = set()
    # /files/123456 (with optional /download)
    for m in re.finditer(r"/files/(\d+)", html):
        try:
            ids.add(int(m.group(1)))
        except ValueError:
            pass
    # api/v1/files/123456
    for m in re.finditer(r"/api/v1/files/(\d+)", html):
        try:
            ids.add(int(m.group(1)))
        except ValueError:
            pass
    return ids


def download_to(session: requests.Session, url: str, target_path: Path) -> None:
    with session.get(url, stream=True, timeout=60) as resp:
        if resp.status_code == 429:
            import time
            time.sleep(int(resp.headers.get("Retry-After", "3")))
            resp.close()
            r2 = session.get(url, stream=True, timeout=60)
            r2.raise_for_status()
            total = int(r2.headers.get("Content-Length") or 0)
            with open(target_path, "wb") as fh:
                pbar = tqdm(total=total or None, unit="B", unit_scale=True, desc=target_path.name, leave=False)
                for chunk in r2.iter_content(chunk_size=262_144):
                    if chunk:
                        fh.write(chunk)
                        pbar.update(len(chunk))
                pbar.close()
            return

        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        with open(target_path, "wb") as fh:
            pbar = tqdm(total=total or None, unit="B", unit_scale=True, desc=target_path.name, leave=False)
            for chunk in resp.iter_content(chunk_size=262_144):
                if chunk:
                    fh.write(chunk)
                    pbar.update(len(chunk))
            pbar.close()


# ----------------- Main -----------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Download ALL files referenced by a chosen Canvas module.")
    parser.add_argument("--domain", required=True, help="Canvas domain (e.g., canvas.odu.edu)")
    parser.add_argument("--course-id", required=True, type=int, help="Canvas course ID")
    parser.add_argument("--token", help="Canvas API token (or set CANVAS_API_TOKEN)")
    parser.add_argument("--choice", type=int, help="Module number to download (same numbering as listing)")
    args = parser.parse_args()

    token = args.token or os.environ.get("CANVAS_API_TOKEN")
    if not token:
        print("Error: provide --token or set CANVAS_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    domain = normalize_domain(args.domain)
    base = f"https://{domain}/api/v1"
    session = build_session(token)

    # Course
    cr = session.get(f"{base}/courses/{args.course_id}", timeout=30)
    if cr.status_code == 401:
        print("Auth failed (401). Check token/permissions.", file=sys.stderr)
        sys.exit(3)
    if cr.status_code == 404:
        print("Course not found (404). Check course ID/enrollment.", file=sys.stderr)
        sys.exit(4)
    cr.raise_for_status()
    course = cr.json()
    course_name = course.get("name") or f"course_{args.course_id}"
    print(f"📚 {course_name} (id={course.get('id')})\n")

    # Modules
    modules = get_all(session, f"{base}/courses/{args.course_id}/modules", params={"per_page": 100})
    if not modules:
        print("No modules are visible to your account.")
        sys.exit(0)

    print("🔹 Modules:")
    for i, m in enumerate(modules, start=1):
        print(f"   {i:2d}. {m.get('name')}  [items: {m.get('items_count', '?')}]")
    print()

    # Choice
    if args.choice is None:
        while True:
            try:
                choice = int(input("What would you like to download? (Enter module number, e.g., 8) > ").strip())
                break
            except ValueError:
                print("Please enter a valid number.")
    else:
        choice = args.choice

    if not (1 <= choice <= len(modules)):
        print(f"Choice {choice} is out of range (1..{len(modules)}).", file=sys.stderr)
        sys.exit(5)

    mod = modules[choice - 1]
    mid = mod.get("id")
    mod_title = mod.get("name") or f"Module {choice}"
    print(f"\n➡️  Selected: {mod_title} (module #{choice})")

    # Get module items
    items = get_all(session, f"{base}/courses/{args.course_id}/modules/{mid}/items", params={"per_page": 100})
    if not items:
        print("This module has no items.")
        sys.exit(0)

    # Resolve file IDs from items
    file_ids: Set[int] = set()

    # 1) File items → content_id is file_id
    for it in items:
        if it.get("type") == "File" and it.get("content_id"):
            try:
                file_ids.add(int(it["content_id"]))
            except (KeyError, ValueError, TypeError):
                pass

    # 2) Page items → fetch page body → scrape file IDs
    for it in items:
        if it.get("type") == "Page":
            slug = it.get("page_url")
            if not slug:
                # fallback: try to pull content id as page id (rare)
                continue
            pr = session.get(f"{base}/courses/{args.course_id}/pages/{slug}", timeout=30)
            if pr.status_code == 403:
                continue  # locked page
            pr.raise_for_status()
            page = pr.json()
            body = page.get("body") or ""
            file_ids |= find_file_ids_in_html(body)

    # 3) Assignment items → attachments
    for it in items:
        if it.get("type") == "Assignment" and it.get("content_id"):
            aid = it.get("content_id")
            ar = session.get(f"{base}/courses/{args.course_id}/assignments/{aid}", timeout=30)
            if ar.status_code == 403:
                continue
            ar.raise_for_status()
            adata = ar.json()
            for att in (adata.get("attachments") or []):
                fid = att.get("id")
                if isinstance(fid, int):
                    file_ids.add(fid)

    if not file_ids:
        print("No downloadable files were found in this module (files may be external links or locked).")
        sys.exit(0)

    # Build output path
    out_dir = Path.home() / "Documents" / sanitize(course_name) / str(choice)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📁 Saving to: {out_dir}")

    # Fetch metadata & download
    downloaded = 0
    skipped = 0
    for fid in sorted(file_ids):
        fr = session.get(f"{base}/files/{fid}", timeout=30)
        if fr.status_code == 403:
            continue  # locked file
        fr.raise_for_status()
        meta = fr.json()
        name = meta.get("display_name") or meta.get("filename") or f"file_{fid}"
        url = meta.get("url") or meta.get("download_url")
        size = int(meta.get("size") or 0)
        if not url:
            continue

        target = out_dir / sanitize(name)
        if target.exists() and size and target.stat().st_size == size:
            skipped += 1
            continue

        try:
            download_to(session, url, target)
            downloaded += 1
        except requests.RequestException as e:
            print(f"  ! Failed: {name} ({e})")

    print(f"\n✅ Done. Downloaded: {downloaded}, skipped: {skipped}. Saved to: {out_dir}")


if __name__ == "__main__":
    main()
