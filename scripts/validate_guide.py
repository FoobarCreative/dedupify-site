#!/usr/bin/env python3
"""Validate a Dedupify guide Markdown file before it is added to _guides.

Usage:
    python3 scripts/validate_guide.py path/to/guide.md [--site-root DIR]

Checks the front matter keys the guide layout, the /guides index and
api/guides.json depend on, plus the house copy rules. Exits 1 on any error.
Warnings do not fail the run.
"""
import argparse
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

CATEGORIES = {"Storage Optimization", "Battery & Power", "Camera & Media", "Performance"}
REQUIRED = [
    "title", "short_title", "description", "category", "priority",
    "estimated_savings", "difficulty", "time_required", "ios_version",
    "date", "last_updated", "item_id",
]
DIFFICULTIES = {"Easy", "Medium", "Hard"}
DASHES = {"—": "em dash", "–": "en dash"}


def split_front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None, text
    return m.group(1), m.group(2)


def parse_front_matter(raw):
    if yaml is not None:
        return yaml.safe_load(raw) or {}
    # Minimal fallback without PyYAML: scalars, lists of scalars, and lists of flat maps.
    data, key = {}, None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and key:
            item = line[4:].strip()
            if ":" in item:
                k, _, v = item.partition(":")
                data.setdefault(key, []).append({k.strip(): v.strip().strip('"')})
            else:
                data.setdefault(key, []).append(item.strip('"'))
            continue
        if line.startswith("    ") and key and isinstance(data.get(key), list) and data[key] and isinstance(data[key][-1], dict):
            k, _, v = line.strip().partition(":")
            data[key][-1][k.strip()] = v.strip().strip('"')
            continue
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip().strip('"')
            data[key] = val if val != "" else data.get(key, [])
    return data


def collect_site(site_root):
    ids, slugs = {}, set()
    guides_dir = os.path.join(site_root, "_guides")
    for name in sorted(os.listdir(guides_dir)):
        if not name.endswith(".md"):
            continue
        slug = name[:-3]
        slugs.add(slug)
        with open(os.path.join(guides_dir, name), encoding="utf-8") as fh:
            fm, _ = split_front_matter(fh.read())
        if fm:
            item = re.search(r'^item_id:\s*"?([^"\n]+)"?', fm, re.M)
            if item:
                ids[item.group(1).strip()] = slug
    pages = set()
    for name in os.listdir(os.path.join(site_root, "_pages")):
        pages.add(os.path.splitext(name)[0])
    return ids, slugs, pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guide")
    ap.add_argument("--site-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()

    errors, warnings = [], []
    with open(args.guide, encoding="utf-8") as fh:
        text = fh.read()
    raw_fm, body = split_front_matter(text)
    if raw_fm is None:
        print("ERROR: no front matter block")
        sys.exit(1)
    fm = parse_front_matter(raw_fm)
    ids, slugs, pages = collect_site(args.site_root)
    slug = os.path.basename(args.guide)[:-3]
    is_existing = slug in slugs

    for key in REQUIRED:
        if key not in fm or fm[key] in ("", None):
            errors.append(f"missing front matter key: {key}")

    if fm.get("category") not in CATEGORIES:
        errors.append(f"category must be one of {sorted(CATEGORIES)}, got {fm.get('category')!r}")
    if fm.get("difficulty") not in DIFFICULTIES:
        warnings.append(f"difficulty is usually one of {sorted(DIFFICULTIES)}, got {fm.get('difficulty')!r}")

    try:
        int(fm.get("priority"))
    except (TypeError, ValueError):
        errors.append("priority must be an integer")

    item_id = str(fm.get("item_id", ""))
    if not re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", item_id):
        errors.append(f"item_id must be snake_case, got {item_id!r}")
    if item_id in ids and ids[item_id] != slug:
        errors.append(f"item_id {item_id!r} is already used by _guides/{ids[item_id]}.md")

    for rel in fm.get("related") or []:
        if rel not in ids:
            errors.append(f"related id {rel!r} does not match any existing item_id")
        if rel == item_id:
            errors.append("related must not include the guide itself")

    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        errors.append(f"file name must be a kebab-case slug, got {slug!r}")
    if not is_existing and slug in pages:
        errors.append(f"slug {slug!r} collides with a page in _pages")
    redirects = fm.get("redirect_from") or []
    if f"/guides/{slug}/" not in redirects:
        warnings.append(f"redirect_from should include /guides/{slug}/ to match the other guides")

    for date_key in ("date", "last_updated"):
        val = str(fm.get(date_key, ""))
        if val and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
            errors.append(f"{date_key} must be YYYY-MM-DD, got {val!r}")

    desc = str(fm.get("description", ""))
    if len(desc) > 160:
        warnings.append(f"description is {len(desc)} characters; keep it at 160 or fewer for search snippets")
    title = str(fm.get("title", ""))
    if len(title) > 70:
        warnings.append(f"title is {len(title)} characters; search engines cut titles past about 60 to 70")

    faq = fm.get("faq")
    if faq is not None:
        if not isinstance(faq, list) or not faq:
            errors.append("faq must be a non-empty list of {q, a} items")
        else:
            for i, item in enumerate(faq, 1):
                if not isinstance(item, dict) or not item.get("q") or not item.get("a"):
                    errors.append(f"faq item {i} needs both q and a")
    elif re.search(r"^##\s+Frequently Asked Questions", body, re.M):
        warnings.append("FAQ lives in the body only; move it to the faq: front matter list for FAQPage schema")

    for ch, name in DASHES.items():
        n = text.count(ch)
        if n:
            errors.append(f"{n} {name}(s) found; replace with a comma, colon or full stop")

    for m in re.finditer(r"\]\((/guides/[^)\s#]+)", body):
        target = m.group(1)
        if target.endswith("/"):
            errors.append(f"internal link {target} has a trailing slash")
            target = target[:-1]
        if target[len("/guides/"):] not in slugs and target[len("/guides/"):] != slug:
            errors.append(f"internal link {target} points to a guide that does not exist")
    for m in re.finditer(r"\]\((https?://[^)]*dedupify\.app[^)]*)\)", body):
        warnings.append(f"absolute link to own site {m.group(1)}; use a root-relative path")

    if not re.search(r"^## Why This Matters", body, re.M):
        warnings.append('body has no "## Why This Matters" section, which the other guides open with')

    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)
    print(f"OK: {slug} passes ({len(warnings)} warning(s))")


if __name__ == "__main__":
    main()
