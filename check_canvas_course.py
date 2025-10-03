#!/usr/bin/env python3
"""
Quick Canvas connectivity check:
- Verifies your token/domain work
- Fetches a single course by ID and prints key info

Usage:
  export CANVAS_API_TOKEN="YOUR_TOKEN"   # or pass --token
  python check_canvas_course.py --domain canvas.odu.edu --course-id 188076
"""

import argparse
import os
import sys
import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Canvas API access for one course.")
    parser.add_argument("--domain", required=True, help="Canvas domain, e.g. canvas.odu.edu")
    parser.add_argument("--course-id", required=True, type=int, help="Canvas course ID")
    parser.add_argument("--token", help="Canvas API token (or set CANVAS_API_TOKEN env var)")
    args = parser.parse_args()

    token = args.token or os.environ.get("CANVAS_API_TOKEN")
    if not token:
        print("Error: provide --token or set CANVAS_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    url = f"https://{args.domain}/api/v1/courses/{args.course_id}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(2)

    if resp.status_code == 401:
        print("Auth failed (401). Check your API token permissions or expiration.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 404:
        print("Course not found (404). Check the course ID and your enrollment.", file=sys.stderr)
        sys.exit(4)

    resp.raise_for_status()
    course = resp.json()

    # Print a minimal, human-friendly summary
    print("✅ Canvas reachable. Course found:")
    print(f"  ID:           {course.get('id')}")
    print(f"  Name:         {course.get('name')}")
    print(f"  Course Code:  {course.get('course_code')}")
    print(f"  Workflow:     {course.get('workflow_state')}")
    print(f"  Starts:       {course.get('start_at')}")
    print(f"  Ends:         {course.get('end_at')}")
    # Uncomment to see all fields:
    # import json; print(json.dumps(course, indent=2))


if __name__ == "__main__":
    main()
