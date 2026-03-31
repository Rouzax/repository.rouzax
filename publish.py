#!/usr/bin/env python3
"""Publish a Kodi addon zip to the repository.rouzax GitHub Pages repo.

Extracts addon metadata from the zip, updates the zips/ directory,
regenerates addons.xml and its MD5 checksum, then commits and pushes.

Usage:
    python3 publish.py /path/to/addon-id-version.zip
"""

import glob
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from typing import Tuple
from xml.etree import ElementTree as ET


REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ZIPS_DIR = os.path.join(REPO_DIR, "zips")


def extract_addon_info(zip_path: str) -> Tuple[str, str, bytes]:
    """Extract addon ID, version, and addon.xml content from a zip.

    The zip is expected to contain <addon-id>/addon.xml at the top level.

    Returns:
        Tuple of (addon_id, version, addon_xml_bytes).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Find addon.xml - it should be at <addon-id>/addon.xml
        addon_xml_paths = [
            n for n in zf.namelist()
            if n.endswith("/addon.xml") and n.count("/") == 1
        ]
        if not addon_xml_paths:
            print("ERROR: No addon.xml found in zip at <addon-id>/addon.xml")
            sys.exit(1)

        addon_xml_path = addon_xml_paths[0]
        addon_xml_bytes = zf.read(addon_xml_path)

        root = ET.fromstring(addon_xml_bytes)
        addon_id = root.get("id", "")
        version = root.get("version", "")

        if not addon_id or not version:
            print("ERROR: addon.xml missing 'id' or 'version' attribute")
            sys.exit(1)

        return addon_id, version, addon_xml_bytes


# Files and patterns that must never appear in a published addon zip.
# If any match is found, the publish is aborted.
BANNED_PATTERNS = [
    ".git/",
    ".git",
    ".github/",
    ".claude/",
    ".claudeignore",
    ".mcp.json",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "LOGGING.md",
    "README.md",
    "pyrightconfig.json",
    ".pyflakes",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".worktrees/",
    "tests/",
    "conftest.py",
    "pytest.ini",
    "docs/",
    "_temp/",
    ".env",
    "credentials",
    ".secrets",
]


def validate_zip_contents(zip_path: str, addon_id: str) -> None:
    """Check zip for dev files, secrets, or other files that must not ship.

    Aborts with an error if any banned patterns are found.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

    # Strip the top-level addon directory prefix for matching
    prefix = addon_id + "/"
    violations = []
    for name in names:
        relative = name[len(prefix):] if name.startswith(prefix) else name
        for pattern in BANNED_PATTERNS:
            if pattern.endswith("/"):
                # Directory pattern - check if path starts with or contains it
                if relative.startswith(pattern) or ("/" + pattern) in relative:
                    violations.append(name)
                    break
            else:
                # File pattern - check basename or exact match
                basename = os.path.basename(relative)
                if basename == pattern or relative == pattern:
                    violations.append(name)
                    break

    if violations:
        print("ERROR: Zip contains files that must not be published:")
        for v in violations:
            print("  - {}".format(v))
        print("\nRebuild the zip with proper exclusions before publishing.")
        sys.exit(1)

    print("  Zip contents validated ({} files, no banned files found)".format(
        len(names)))


def remove_old_zips(addon_id: str) -> None:
    """Remove old zip files for the given addon ID."""
    addon_dir = os.path.join(ZIPS_DIR, addon_id)
    if not os.path.isdir(addon_dir):
        return

    for old_zip in glob.glob(os.path.join(addon_dir, "*.zip")):
        print("  Removing old zip: {}".format(os.path.basename(old_zip)))
        os.remove(old_zip)


def copy_new_zip(zip_path: str, addon_id: str, version: str) -> None:
    """Copy the new zip into zips/<addon-id>/<addon-id>-<version>.zip."""
    addon_dir = os.path.join(ZIPS_DIR, addon_id)
    os.makedirs(addon_dir, exist_ok=True)

    dest = os.path.join(addon_dir, "{}-{}.zip".format(addon_id, version))
    shutil.copy2(zip_path, dest)
    print("  Copied zip to: zips/{}/{}".format(addon_id, os.path.basename(dest)))


def extract_addon_xml(addon_id: str, addon_xml_bytes: bytes) -> None:
    """Write addon.xml into zips/<addon-id>/addon.xml."""
    addon_dir = os.path.join(ZIPS_DIR, addon_id)
    os.makedirs(addon_dir, exist_ok=True)

    dest = os.path.join(addon_dir, "addon.xml")
    with open(dest, "wb") as f:
        f.write(addon_xml_bytes)
    print("  Extracted addon.xml to: zips/{}/addon.xml".format(addon_id))


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Add indentation to an XML element tree (Python 3.8 compatible).

    ET.indent() was added in Python 3.9, so this provides the same
    functionality for older versions.
    """
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():  # type: ignore[possibly-undefined]
            child.tail = indent  # type: ignore[possibly-undefined]
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


def regenerate_addons_xml() -> None:
    """Merge all zips/*/addon.xml files into zips/addons.xml."""
    addons_root = ET.Element("addons")

    # Find all individual addon.xml files
    pattern = os.path.join(ZIPS_DIR, "*", "addon.xml")
    addon_xml_files = sorted(glob.glob(pattern))

    for addon_xml_path in addon_xml_files:
        tree = ET.parse(addon_xml_path)
        addon_element = tree.getroot()
        addons_root.append(addon_element)
        addon_id = addon_element.get("id", "unknown")
        version = addon_element.get("version", "unknown")
        print("  Including: {} v{}".format(addon_id, version))

    # Write addons.xml with XML declaration
    addons_xml_path = os.path.join(ZIPS_DIR, "addons.xml")
    tree = ET.ElementTree(addons_root)
    _indent_xml(addons_root)
    with open(addons_xml_path, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True)
        f.write(b"\n")

    print("  Wrote: zips/addons.xml ({} addons)".format(len(addon_xml_files)))


def regenerate_addons_xml_md5() -> None:
    """Generate MD5 checksum of addons.xml content."""
    addons_xml_path = os.path.join(ZIPS_DIR, "addons.xml")
    with open(addons_xml_path, "rb") as f:
        content = f.read()

    md5_hex = hashlib.md5(content).hexdigest()

    md5_path = os.path.join(ZIPS_DIR, "addons.xml.md5")
    with open(md5_path, "w") as f:
        f.write(md5_hex)

    print("  Wrote: zips/addons.xml.md5 ({})".format(md5_hex))


def git_commit_and_push(addon_id: str, version: str) -> None:
    """Stage changes, commit, and push if there are changes."""
    # Stage all changes in zips/
    subprocess.run(
        ["git", "add", "zips/"],
        cwd=REPO_DIR,
        check=True,
    )

    # Check if there are staged changes
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=REPO_DIR,
    )

    if result.returncode == 0:
        print("  No changes to commit, skipping.")
        return

    # Commit
    message = "Update {} to {}".format(addon_id, version)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=REPO_DIR,
        check=True,
    )
    print("  Committed: {}".format(message))

    # Push
    subprocess.run(
        ["git", "push"],
        cwd=REPO_DIR,
        check=True,
    )
    print("  Pushed to remote.")


def main() -> None:
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python3 publish.py /path/to/addon-version.zip")
        sys.exit(1)

    zip_path = os.path.abspath(sys.argv[1])

    if not os.path.isfile(zip_path):
        print("ERROR: File not found: {}".format(zip_path))
        sys.exit(1)

    if not zip_path.endswith(".zip"):
        print("ERROR: Expected a .zip file, got: {}".format(zip_path))
        sys.exit(1)

    print("Publishing addon zip: {}".format(zip_path))

    # Step 1: Extract addon info from zip
    print("\n[1/7] Extracting addon info...")
    addon_id, version, addon_xml_bytes = extract_addon_info(zip_path)
    print("  Addon: {} v{}".format(addon_id, version))

    # Step 2: Validate zip contents
    print("\n[2/7] Validating zip contents...")
    validate_zip_contents(zip_path, addon_id)

    # Step 3: Remove old zips
    print("\n[3/7] Removing old zips...")
    remove_old_zips(addon_id)

    # Step 4: Copy new zip
    print("\n[4/7] Copying new zip...")
    copy_new_zip(zip_path, addon_id, version)

    # Step 5: Extract addon.xml
    print("\n[5/7] Extracting addon.xml...")
    extract_addon_xml(addon_id, addon_xml_bytes)

    # Step 6: Regenerate addons.xml
    print("\n[6/7] Regenerating addons.xml...")
    regenerate_addons_xml()

    # Step 7: Regenerate addons.xml.md5
    print("\n[7/7] Regenerating addons.xml.md5...")
    regenerate_addons_xml_md5()

    # Git commit and push
    print("\nCommitting and pushing...")
    git_commit_and_push(addon_id, version)

    print("\nDone! {} v{} published to repository.".format(addon_id, version))


if __name__ == "__main__":
    main()
