#!/usr/bin/env python3
"""
Canvas Grabber (interactive CLI)
- Ask for domain, token (hidden), and show your courses to pick one.
- List modules and let you choose multiple (e.g., "8,9,6" or "5-7").
- Download ALL files from those modules:
    * File items (direct)
    * Files linked inside Pages (scrape file IDs from page HTML)
    * Assignment attachments
- Saves to: ~/Documents/<Course Name>/<Module Title>/

Requirements:
  pip install requests tqdm
  # optional (colors): pip install colorama
"""

from __future__ import annotations

import os
import re
import sys
import getpass
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter, Retry
from tqdm import tqdm

# Optional colors
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init()
    C_PRIMARY = Fore.CYAN
    C_OK = Fore.GREEN
    C_WARN = Fore.YELLOW
    C_ERR = Fore.RED
    C_DIM = Style.DIM
    C_RESET = Style.RESET_ALL
except Exception:  # no colorama
    class _NoColor:
        def __getattr__(self, _): return ""
    Fore = Style = _NoColor()
    C_PRIMARY = C_OK = C_WARN = C_ERR = C_DIM = C_RESET = ""

BANNER = r"""
 ██████╗ █████╗ ███╗   ██╗██╗   ██╗ █████╗ ███████╗     ██████╗ ██████╗  █████╗ ██████╗ ██████╗ ███████╗██████╗ 
██╔════╝██╔══██╗████╗  ██║██║   ██║██╔══██╗██╔════╝    ██╔════╝ ██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗
██║     ███████║██╔██╗ ██║██║   ██║███████║███████╗    ██║  ███╗██████╔╝███████║██████╔╝██████╔╝█████╗  ██████╔╝
██║     ██╔══██║██║╚██╗██║╚██╗ ██╔╝██╔══██║╚════██║    ██║   ██║██╔══██╗██╔══██║██╔══██╗██╔══██╗██╔══╝  ██╔══██╗
╚██████╗██║  ██║██║ ╚████║ ╚████╔╝ ██║  ██║███████║    ╚██████╔╝██║  ██║██║  ██║██████╔╝██████╔╝███████╗██║  ██║
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚═══╝  ╚═╝  ╚═╝╚══════╝     ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
                                                                                                                
"""

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


_ILLEGAL = r'[<>:"/\\|?*\x00-\x1F]'
def sanitize(name: str) -> str:
    return re.sub(_ILLEGAL, "_", name).strip(" .")


def find_file_ids_in_html(html: str) -> Set[int]:
    """
    Find Canvas file IDs inside Page HTML. Handles both:
      - /files/123456 (with or without /download)
      - /api/v1/files/123456
    """
    ids: Set[int] = set()
    for m in re.finditer(r"/files/(\d+)", html):
        try:
            ids.add(int(m.group(1)))
        except ValueError:
            pass
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


def parse_choices(raw: str, maxnum: int) -> List[int]:
    """
    Parse input like "8,9,6" (and supports ranges like "5-7").
    Returns a unique, ordered list of valid module numbers.
    """
    nums: List[int] = []
    seen = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            try:
                s, e = int(start), int(end)
                if s > e:
                    s, e = e, s
                for n in range(s, e + 1):
                    if 1 <= n <= maxnum and n not in seen:
                        seen.add(n)
                        nums.append(n)
            except ValueError:
                continue
        else:
            try:
                n = int(part)
                if 1 <= n <= maxnum and n not in seen:
                    seen.add(n)
                    nums.append(n)
            except ValueError:
                continue
    return nums


# ----------------- Interactive Flow -----------------

def main() -> None:
    print(C_PRIMARY + BANNER + C_RESET)
    print(C_DIM + "Welcome to Canvas Grabber — download course content fast.\n" + C_RESET)

    # ---- 1) Gather creds/target ----
    domain_in = input("Canvas domain (e.g., canvas.odu.edu): ").strip()
    domain = normalize_domain(domain_in if domain_in else "canvas.instructure.com")

    # prefer env var first, otherwise prompt (hidden)
    token = os.environ.get("CANVAS_API_TOKEN")
    if not token:
        token = getpass.getpass("Canvas API token (input hidden): ").strip()
    if not token:
        print(C_ERR + "No token provided. Exiting." + C_RESET)
        sys.exit(1)

    session = build_session(token)
    base = f"https://{domain}/api/v1"

    # ---- 2) Fetch active courses & choose one ----
    try:
        courses = get_all(session, f"{base}/courses", params={"per_page": 100, "enrollment_state": "active"})
    except requests.RequestException as e:
        print(C_ERR + f"Failed to list courses: {e}" + C_RESET)
        sys.exit(2)

    if not courses:
        print(C_WARN + "No active courses found for this token." + C_RESET)
        sys.exit(0)

    # Sort by name for nicer display
    courses_sorted = sorted(courses, key=lambda c: (c.get("name") or "").lower())
    print("\n" + C_PRIMARY + "📚 Your courses:" + C_RESET)
    for i, c in enumerate(courses_sorted, start=1):
        name = c.get("name") or f"(Unnamed course {c.get('id')})"
        code = c.get("course_code") or ""
        print(f"  {i:2d}. {name} {C_DIM}[{code}] {C_RESET}")

    # Pick one
    while True:
        raw = input("\nSelect a course number: ").strip()
        try:
            idx = int(raw)
            if 1 <= idx <= len(courses_sorted):
                break
            print("Please enter a valid number from the list.")
        except ValueError:
            print("Please enter a valid number.")

    course = courses_sorted[idx - 1]
    course_id = int(course["id"])
    course_name = course.get("name") or f"course_{course_id}"

    # Confirm access
    cr = session.get(f"{base}/courses/{course_id}", timeout=30)
    if cr.status_code == 401:
        print(C_ERR + "Auth failed (401). Check token/permissions." + C_RESET)
        sys.exit(3)
    if cr.status_code == 404:
        print(C_ERR + "Course not found (404). Check enrollment." + C_RESET)
        sys.exit(4)
    cr.raise_for_status()

    print(f"\n{C_OK}✓ Selected:{C_RESET} {course_name} {C_DIM}(id={course_id}){C_RESET}\n")

    # ---- 3) Show modules and pick multiple ----
    modules = get_all(session, f"{base}/courses/{course_id}/modules", params={"per_page": 100})
    if not modules:
        print(C_WARN + "No modules are visible in this course." + C_RESET)
        sys.exit(0)

    print(C_PRIMARY + "🔹 Modules:" + C_RESET)
    for i, m in enumerate(modules, start=1):
        print(f"   {i:2d}. {m.get('name')}  {C_DIM}[items: {m.get('items_count','?')}]"+C_RESET)

    raw_choices = input(
        "\nWhat would you like to download? (e.g., 8,9,6 or 5-7) > "
    ).strip()
    choices = parse_choices(raw_choices, len(modules))
    if not choices:
        print(C_WARN + "No valid module numbers selected." + C_RESET)
        sys.exit(0)

    base_out_dir = Path.home() / "Documents" / sanitize(course_name)
    base_out_dir.mkdir(parents=True, exist_ok=True)

    grand_downloaded = 0
    grand_skipped = 0

    for choice in choices:
        mod = modules[choice - 1]
        mid = mod.get("id")
        mod_title = mod.get("name") or f"Module {choice}"
        mod_dir = base_out_dir / sanitize(mod_title)
        mod_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n➡️  {C_PRIMARY}Module{C_RESET}: {mod_title}  {C_DIM}(#{choice}){C_RESET}")
        print(f"📁 Saving to: {mod_dir}")

        items = get_all(session, f"{base}/courses/{course_id}/modules/{mid}/items", params={"per_page": 100})
        if not items:
            print("  (This module has no items.)")
            continue

        file_ids: Set[int] = set()

        # A) Direct File items
        for it in items:
            if it.get("type") == "File" and it.get("content_id"):
                try:
                    file_ids.add(int(it["content_id"]))
                except (KeyError, ValueError, TypeError):
                    pass

        # B) Page items -> parse page body for file links
        for it in items:
            if it.get("type") == "Page":
                slug = it.get("page_url")
                if not slug:
                    continue
                pr = session.get(f"{base}/courses/{course_id}/pages/{slug}", timeout=30)
                if pr.status_code == 403:
                    continue
                pr.raise_for_status()
                body = (pr.json().get("body") or "")
                file_ids |= find_file_ids_in_html(body)

        # C) Assignment items -> attachments
        for it in items:
            if it.get("type") == "Assignment" and it.get("content_id"):
                aid = it.get("content_id")
                ar = session.get(f"{base}/courses/{course_id}/assignments/{aid}", timeout=30)
                if ar.status_code == 403:
                    continue
                ar.raise_for_status()
                for att in (ar.json().get("attachments") or []):
                    fid = att.get("id")
                    if isinstance(fid, int):
                        file_ids.add(fid)

        if not file_ids:
            print("  (No downloadable Canvas files found in this module.)")
            continue

        downloaded = 0
        skipped = 0
        for fid in sorted(file_ids):
            fr = session.get(f"{base}/files/{fid}", timeout=30)
            if fr.status_code == 403:
                continue
            fr.raise_for_status()
            meta = fr.json()
            name = meta.get("display_name") or meta.get("filename") or f"file_{fid}"
            url = meta.get("url") or meta.get("download_url")
            size = int(meta.get("size") or 0)
            if not url:
                continue

            target = mod_dir / sanitize(name)
            if target.exists() and size and target.stat().st_size == size:
                skipped += 1
                continue

            try:
                download_to(session, url, target)
                downloaded += 1
            except requests.RequestException as e:
                print(f"  ! Failed: {name} ({e})")

        grand_downloaded += downloaded
        grand_skipped += skipped
        print(f"  {C_OK}✓ Module done.{C_RESET} Downloaded: {downloaded}, skipped: {skipped}")

    print(f"\n{C_OK}✓ All done.{C_RESET} Downloaded: {grand_downloaded}, skipped: {grand_skipped}")
    print(f"Saved under: {C_PRIMARY}{base_out_dir}{C_RESET}")


if __name__ == "__main__":
    main()

