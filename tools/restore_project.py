#!/usr/bin/env python3
"""Restore exact project bytes from the public GUOXUE release (Python 3.9+).

Only the Python standard library is used. Archives are streamed and members are
never extracted with extractall(). The manifests remain the source of truth for
all original paths, including symlinks intentionally not recreated.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile


CHUNK = 4 * 1024 * 1024
SCOPES = {"final": {"desktop", "final_view", "final_docs"},
          "history": {"history"},
          "all": {"desktop", "final_view", "final_docs", "history"}}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST_FILES = {"project-files.jsonl.gz", "objects.jsonl.gz",
                  "release-assets.json", "directories.jsonl.gz"}


class RestoreError(Exception):
    """An integrity, path, or existing-file conflict prevented restoration."""


def require_hash(value, label):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RestoreError("Invalid SHA-256 in " + label)
    return value


def require_size(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RestoreError("Invalid byte count in " + label)
    return value


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RestoreError("Duplicate JSON key in manifest-checksums.json: " + key)
        result[key] = value
    return result


def relative_path(value, label="path"):
    # Backslashes and drive names are refused so the same manifest is safe on
    # Windows and POSIX. The original Mac source inventory has neither.
    if (not isinstance(value, str) or not value or "\x00" in value or "\\" in value
            or re.match(r"^[A-Za-z]:", value)):
        raise RestoreError("Unsafe " + label + ": " + repr(value))
    parts = value.split("/")
    if PurePosixPath(value).is_absolute() or any(p in ("", ".", "..") for p in parts):
        raise RestoreError("Unsafe " + label + ": " + repr(value))
    return value


def json_lines(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except (ValueError, TypeError) as exc:
                    raise RestoreError("Invalid JSON at %s:%s: %s" %
                                       (path, line_number, exc)) from exc
                if not isinstance(item, dict):
                    raise RestoreError("Expected an object at %s:%s" % (path, line_number))
                yield item
    except OSError as exc:
        raise RestoreError("Cannot read manifest %s: %s" % (path, exc)) from exc


def stream_copy(source, destination, expected_bytes, expected_hash, label):
    digest = hashlib.sha256()
    total = 0
    while True:
        block = source.read(CHUNK)
        if not block:
            break
        total += len(block)
        if total > expected_bytes:
            raise RestoreError("Byte count exceeds the manifest: " + label)
        digest.update(block)
        destination.write(block)
    if total != expected_bytes or digest.hexdigest() != expected_hash:
        raise RestoreError("SHA-256/byte count mismatch: " + label)
    return total


def file_matches(path, expected_bytes, expected_hash):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != expected_bytes:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest() == expected_hash


class Restorer:
    def __init__(self, args):
        self.args = args
        self.root = args.root.expanduser().resolve()
        self.cache = (args.cache.expanduser().resolve() if args.cache else
                      self.root / ".restore-cache")
        self.manifests = args.manifest_dir.expanduser().resolve()
        self.files = []
        self.directories = {}
        self.objects = {}
        self.assets = {}
        self.groups = {}
        self.needed = {}
        self.valid_sources = {}
        self.symlinks = []
        self.skipped_links = []
        self.checked_assets = {}
        self.zip_name = None
        self.zip_handle = None
        self.original_directory_modes = {}
        self.completed = False
        self.counts = {"selected_files": 0, "already_correct": 0,
                       "restored_files": 0, "restored_symlinks": 0,
                       "skipped_symlinks": 0, "downloaded_assets": 0}

    def load(self):
        self.verify_manifest_bundle()
        selected = SCOPES[self.args.scope]
        seen = set()
        for row in json_lines(self.manifests / "project-files.jsonl.gz"):
            if row.get("scope") not in selected:
                continue
            path = relative_path(row.get("path"))
            if path in seen:
                raise RestoreError("Duplicate project path: " + path)
            seen.add(path)
            require_size(row.get("bytes"), path)
            require_hash(row.get("sha256"), path)
            mode = row.get("mode", 0o644)
            if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
                raise RestoreError("Invalid mode: " + path)
            if row.get("kind") == "file":
                self.files.append(row)
                self.groups.setdefault(row["sha256"], []).append(row)
            elif row.get("kind") == "symlink":
                target = row.get("link_target")
                if not isinstance(target, str) or "\x00" in target:
                    raise RestoreError("Missing/invalid symlink metadata: " + path)
                raw = os.fsencode(target)
                if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                    raise RestoreError("Symlink metadata hash mismatch: " + path)
                self.symlinks.append(row)
            else:
                raise RestoreError("Unsupported file kind: " + path)
        if not seen:
            raise RestoreError("No project paths selected for scope " + self.args.scope)
        for path in seen:
            parent = PurePosixPath(path).parent
            while str(parent) != ".":
                if str(parent) in seen:
                    raise RestoreError("A file/symlink is also a parent directory: " + str(parent))
                parent = parent.parent
        for row in json_lines(self.manifests / "directories.jsonl.gz"):
            if row.get("scope") not in selected:
                continue
            path = relative_path(row.get("path"), "directory path")
            if path in seen or path in self.directories:
                raise RestoreError("Conflicting/duplicate directory path: " + path)
            mode = row.get("mode", 0o755)
            if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
                raise RestoreError("Invalid directory mode: " + path)
            if "mtime_ns" in row:
                require_size(row["mtime_ns"], path + " mtime_ns")
            self.directories[path] = row
            parent = PurePosixPath(path).parent
            while str(parent) != ".":
                if str(parent) in seen:
                    raise RestoreError("A file/symlink is also a directory parent: " + str(parent))
                parent = parent.parent
        for row in json_lines(self.manifests / "objects.jsonl.gz"):
            sha = require_hash(row.get("sha256"), "object")
            require_size(row.get("bytes"), sha)
            if sha in self.objects:
                raise RestoreError("Duplicate object: " + sha)
            self.objects[sha] = row
        try:
            with (self.manifests / "release-assets.json").open(encoding="utf-8") as handle:
                release = json.load(handle)
            asset_rows = release["assets"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RestoreError("Cannot read release-assets.json: " + str(exc)) from exc
        for row in asset_rows:
            name = relative_path(row.get("name"), "asset name")
            if "/" in name or name in self.assets:
                raise RestoreError("Invalid/duplicate asset name: " + name)
            require_hash(row.get("sha256"), name)
            require_size(row.get("bytes"), name)
            url = row.get("browser_download_url")
            if not isinstance(url, str) or urllib.parse.urlparse(url).scheme not in {"https", "http", "file"}:
                raise RestoreError("Missing/unsupported download URL: " + name)
            self.assets[name] = row
        for sha, rows in self.groups.items():
            obj = self.objects.get(sha)
            if not obj or any(row["bytes"] != obj["bytes"] for row in rows):
                raise RestoreError("Missing/inconsistent storage object: " + sha)
            if obj.get("storage") == "zip_member":
                self.require_asset(obj.get("asset"))
                relative_path(obj.get("member"), "ZIP member")
            elif obj.get("storage") == "parts":
                parts = obj.get("parts")
                if not isinstance(parts, list) or not parts:
                    raise RestoreError("Missing parts: " + sha)
                total = 0
                for part in parts:
                    asset = self.require_asset(part.get("asset"))
                    if (require_size(part.get("bytes"), sha) != asset["bytes"] or
                            require_hash(part.get("sha256"), sha) != asset["sha256"]):
                        raise RestoreError("Part metadata differs from its asset: " + sha)
                    total += part["bytes"]
                if total != obj["bytes"]:
                    raise RestoreError("Part sizes do not sum to the object size: " + sha)
            else:
                raise RestoreError("Unsupported storage type: " + sha)
        self.counts["selected_files"] = len(self.files)

    def verify_manifest_bundle(self):
        # The checksum table is anchored by the repository commit/release, not a
        # digital signature. Verify the entire published path set before parsing
        # scope rows: a valid gzip with a missing row must never shrink an audit.
        path = self.manifests / "manifest-checksums.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                table = json.load(handle, object_pairs_hook=reject_duplicate_keys)
        except (OSError, ValueError, TypeError) as exc:
            raise RestoreError("Cannot read manifest-checksums.json: " + str(exc)) from exc
        if (not isinstance(table, dict) or type(table.get("schema_version")) is not int
                or table["schema_version"] != 1):
            raise RestoreError("Unsupported/missing manifest-checksums.json schema_version")
        files = table.get("files")
        if not isinstance(files, dict) or set(files) != MANIFEST_FILES:
            raise RestoreError("manifest-checksums.json must list exactly all four required manifests")
        for name in sorted(MANIFEST_FILES):
            row = files[name]
            if not isinstance(row, dict):
                raise RestoreError("Invalid checksum metadata: " + name)
            size = require_size(row.get("bytes"), name)
            sha = require_hash(row.get("sha256"), name)
            try:
                matches = file_matches(self.manifests / name, size, sha)
            except OSError as exc:
                raise RestoreError("Cannot check manifest %s: %s" % (name, exc)) from exc
            if not matches:
                raise RestoreError("Manifest SHA-256/byte count mismatch: " + name)

    def require_asset(self, name):
        if name not in self.assets:
            raise RestoreError("Missing release asset metadata: " + str(name))
        return self.assets[name]

    def target(self, path):
        return self.root.joinpath(*relative_path(path).split("/"))

    def inspect_path(self, path, include_leaf=False):
        parts = relative_path(path).split("/")
        cursor = self.root
        if self.root.exists() and not self.root.is_dir():
            raise RestoreError("Restore root is not a directory: " + str(self.root))
        for part in (parts if include_leaf else parts[:-1]):
            cursor = cursor / part
            try:
                info = cursor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                raise RestoreError("Refusing a symlink in a destination path: " + str(cursor))
            if not stat.S_ISDIR(info.st_mode):
                raise RestoreError("Destination parent is not a directory: " + str(cursor))

    def allowed_link(self, row):
        target = row["link_target"]
        if (not target or PurePosixPath(target).is_absolute() or "\\" in target
                or re.match(r"^[A-Za-z]:", target)):
            return False, "external/absolute or unsupported link target"
        parts = list(PurePosixPath(row["path"]).parent.parts)
        for part in target.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    return False, "link target would leave the restore root"
                parts.pop()
            else:
                parts.append(part)
        if parts:
            candidate = "/".join(parts)
            self.inspect_path(candidate)
            path = self.target(candidate)
            if path.is_symlink():
                return False, "link target is another existing symlink"
        return True, ""

    def preflight(self):
        problems = []
        for path in self.directories:
            self.inspect_path(path, include_leaf=True)
            if self.args.verify_only and not self.target(path).is_dir():
                problems.append("Missing directory: " + path)
        for sha, rows in self.groups.items():
            missing = []
            for row in rows:
                path = row["path"]
                self.inspect_path(path)
                target = self.target(path)
                try:
                    info = target.lstat()
                except FileNotFoundError:
                    info = None
                if info and stat.S_ISLNK(info.st_mode):
                    problems.append("Refusing an existing destination symlink: " + path)
                elif info and not stat.S_ISREG(info.st_mode):
                    problems.append("Destination is not a regular file: " + path)
                elif info and file_matches(target, row["bytes"], sha):
                    self.counts["already_correct"] += 1
                    self.valid_sources.setdefault(sha, target)
                elif self.args.verify_only:
                    problems.append(("Incorrect file: " if info else "Missing file: ") + path)
                elif info and not self.args.replace_invalid:
                    problems.append("Incorrect existing file (use --replace-invalid to replace): " + path)
                else:
                    missing.append(row)
            if missing:
                self.needed[sha] = missing
        for row in self.symlinks:
            self.inspect_path(row["path"])
            allowed, reason = self.allowed_link(row)
            if not self.args.restore_symlinks or not allowed:
                row = dict(row, restore_note=(reason or "symlink restoration was not requested"))
                self.skipped_links.append(row)
                self.counts["skipped_symlinks"] += 1
                continue
            target = self.target(row["path"])
            if target.is_symlink() and os.readlink(target) == row["link_target"]:
                continue
            if self.args.verify_only:
                problems.append("Missing/incorrect symlink: " + row["path"])
            elif os.path.lexists(target) and not self.args.replace_invalid:
                problems.append("Incorrect existing symlink target (use --replace-invalid): " + row["path"])
            elif target.exists() and target.is_dir() and not target.is_symlink():
                problems.append("Refusing to replace a directory with a symlink: " + row["path"])
        if problems:
            shown = problems[:20]
            if len(problems) > len(shown):
                shown.append("... and %s more conflicts" % (len(problems) - len(shown)))
            raise RestoreError("Preflight failed; no assets downloaded:\n  " + "\n  ".join(shown))

    def writable_directory(self, directory):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RestoreError("Unsafe destination directory: " + str(directory))
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o700 != 0o700:
            self.original_directory_modes.setdefault(directory, mode)
            directory.chmod(mode | 0o700)

    def ensure_directory(self, relative=None):
        self.root.mkdir(parents=True, exist_ok=True)
        self.writable_directory(self.root)
        cursor = self.root
        if relative:
            for part in relative_path(relative).split("/"):
                cursor = cursor / part
                if not os.path.lexists(cursor):
                    cursor.mkdir(mode=0o700)
                self.writable_directory(cursor)

    def ensure_parent(self, relative):
        self.inspect_path(relative)
        parent = str(PurePosixPath(relative).parent)
        self.ensure_directory(None if parent == "." else parent)

    def get_asset(self, name):
        if name in self.checked_assets:
            return self.checked_assets[name]
        row = self.require_asset(name)
        self.ensure_cache()
        asset_dir = self.cache / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        if asset_dir.is_symlink():
            raise RestoreError("Refusing a symlink cache directory: " + str(asset_dir))
        destination = asset_dir / name
        if os.path.lexists(destination):
            if destination.is_symlink() or not file_matches(destination, row["bytes"], row["sha256"]):
                if not self.args.replace_invalid:
                    raise RestoreError("Incorrect cached asset (use --replace-invalid): " + str(destination))
            else:
                self.checked_assets[name] = destination
                return destination
        print("Downloading %s (%s bytes)" % (name, row["bytes"]), flush=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".download-", dir=asset_dir, delete=False) as output:
                temp_name = Path(output.name)
                request = urllib.request.Request(row["browser_download_url"],
                                                 headers={"User-Agent": "GUOXUE-exact-restore/1"})
                with urllib.request.urlopen(request, timeout=60) as source:
                    stream_copy(source, output, row["bytes"], row["sha256"], name)
            os.replace(temp_name, destination)
            temp_name = None
        finally:
            if temp_name is not None:
                temp_name.unlink(missing_ok=True)
        self.checked_assets[name] = destination
        self.counts["downloaded_assets"] += 1
        return destination

    def ensure_cache(self):
        # An explicit --cache can intentionally point outside --root. An implicit
        # cache must not follow a pre-existing link out of the destination.
        if self.cache.is_symlink():
            raise RestoreError("Refusing a symlink cache directory: " + str(self.cache))
        self.cache.mkdir(parents=True, exist_ok=True)

    def zip_for(self, name):
        if name != self.zip_name:
            if self.zip_handle is not None:
                self.zip_handle.close()
            self.zip_handle = zipfile.ZipFile(self.get_asset(name), "r")
            self.zip_name = name
        return self.zip_handle

    def install(self, row, writer):
        self.ensure_parent(row["path"])
        target = self.target(row["path"])
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".guoxue-restore-", dir=target.parent,
                                             delete=False) as output:
                temporary = Path(output.name)
                writer(output)
            # Check parents again before committing the verified temporary file.
            self.inspect_path(row["path"])
            # Keep it readable while exact-content duplicates are copied. All
            # original file modes are applied after the data phase succeeds.
            temporary.chmod(0o600)
            if not self.args.replace_invalid:
                try:
                    # Both names are in the same directory/filesystem. Creating
                    # a hard link is an atomic no-replace commit: a file created
                    # during a long download can never be silently overwritten.
                    os.link(temporary, target)
                except FileExistsError:
                    info = target.lstat()
                    if (stat.S_ISREG(info.st_mode) and
                            file_matches(target, row["bytes"], row["sha256"])):
                        self.counts["already_correct"] += 1
                        return target
                    raise RestoreError("Destination appeared/changed during restoration; "
                                       "refusing to overwrite (use --replace-invalid): " + row["path"])
                temporary.unlink()
                temporary = None
            else:
                # Replacement was explicitly requested, but it still must not
                # turn a directory or symlink into a file after preflight.
                try:
                    info = target.lstat()
                except FileNotFoundError:
                    info = None
                if info is not None and not stat.S_ISREG(info.st_mode):
                    raise RestoreError("Destination became a symlink/non-regular file; "
                                       "refusing replacement: " + row["path"])
                if (info is not None and
                        file_matches(target, row["bytes"], row["sha256"])):
                    self.counts["already_correct"] += 1
                    return target
                os.replace(temporary, target)
                temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.counts["restored_files"] += 1
        return target

    def restore_object(self, sha, rows):
        obj = self.objects[sha]

        def write_object(output):
            if sha in self.valid_sources:
                with self.valid_sources[sha].open("rb") as source:
                    stream_copy(source, output, obj["bytes"], sha, str(self.valid_sources[sha]))
            elif obj["storage"] == "zip_member":
                archive = self.zip_for(obj["asset"])
                info = archive.getinfo(obj["member"])
                if info.is_dir() or info.file_size != obj["bytes"]:
                    raise RestoreError("ZIP member byte count mismatch: " + obj["member"])
                with archive.open(info, "r") as source:
                    stream_copy(source, output, obj["bytes"], sha, obj["member"])
            else:
                digest = hashlib.sha256()
                total = 0
                for part in obj["parts"]:
                    with self.get_asset(part["asset"]).open("rb") as source:
                        while True:
                            block = source.read(CHUNK)
                            if not block:
                                break
                            total += len(block)
                            digest.update(block)
                            output.write(block)
                if total != obj["bytes"] or digest.hexdigest() != sha:
                    raise RestoreError("Reassembled object SHA-256/byte count mismatch: " + sha)

        first = self.install(rows[0], write_object)
        for row in rows[1:]:
            def duplicate(output, first=first):
                with first.open("rb") as source:
                    stream_copy(source, output, obj["bytes"], sha, row["path"])
            self.install(row, duplicate)

    def restore_links(self):
        skipped = {row["path"] for row in self.skipped_links}
        for row in self.symlinks:
            if row["path"] in skipped:
                continue
            target = self.target(row["path"])
            if target.is_symlink() and os.readlink(target) == row["link_target"]:
                continue
            self.ensure_parent(row["path"])
            # Link targets may have been restored since preflight; validate again.
            allowed, reason = self.allowed_link(row)
            if not allowed:
                raise RestoreError("Unsafe symlink: %s (%s)" % (row["path"], reason))
            try:
                # symlink() also has atomic no-replace semantics. A leaf created
                # after preflight must not be unlinked without explicit consent.
                os.symlink(row["link_target"], target)
            except FileExistsError:
                if target.is_symlink() and os.readlink(target) == row["link_target"]:
                    continue
                if not self.args.replace_invalid:
                    raise RestoreError("Symlink destination appeared/changed during restoration; "
                                       "refusing to overwrite (use --replace-invalid): " + row["path"])
                if target.is_dir() and not target.is_symlink():
                    raise RestoreError("Refusing to replace a directory with a symlink: " + row["path"])
                target.unlink()
                # If another operation creates a new leaf after unlink(), this
                # atomic create fails instead of overwriting that new entry.
                os.symlink(row["link_target"], target)
            self.counts["restored_symlinks"] += 1

    def finish_directories(self):
        modes = dict(self.original_directory_modes)
        for path, row in self.directories.items():
            modes[self.target(path)] = row.get("mode", 0o755)
        # Children first: a read-only parent must never block unfinished files.
        for directory in sorted(modes, key=lambda path: len(path.parts), reverse=True):
            relative = directory.relative_to(self.root).as_posix()
            if relative != ".":
                self.inspect_path(relative, include_leaf=True)
            row = self.directories.get(relative)
            if row and "mtime_ns" in row:
                os.utime(directory, ns=(row["mtime_ns"], row["mtime_ns"]))
            directory.chmod(modes[directory])

    def finish_file_modes(self):
        for row in self.files:
            self.inspect_path(row["path"])
            path = self.target(row["path"])
            if not stat.S_ISREG(path.lstat().st_mode):
                raise RestoreError("File changed during restoration: " + row["path"])
            path.chmod(row.get("mode", 0o644))

    def run(self):
        self.load()
        self.preflight()
        if not self.args.verify_only:
            for path in sorted(self.directories, key=lambda value: (value.count("/"), value)):
                self.ensure_directory(path)
            object_order = sorted(self.needed, key=lambda sha: (
                self.objects[sha]["storage"], self.objects[sha].get("asset", ""), sha))
            for index, sha in enumerate(object_order, 1):
                self.restore_object(sha, self.needed[sha])
                if index % 100 == 0:
                    print("Restored %s/%s required content objects" %
                          (index, len(self.needed)), flush=True)
            self.restore_links()
            if self.skipped_links:
                self.ensure_cache()
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(prefix=".symlinks-", dir=self.cache,
                                                     delete=False, mode="w", encoding="utf-8") as handle:
                        temporary = Path(handle.name)
                        for row in self.skipped_links:
                            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
                    os.replace(temporary, self.cache / "skipped-symlinks.jsonl")
                    temporary = None
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            self.finish_file_modes()
            self.finish_directories()
            self.completed = True
        if self.skipped_links:
            print("Symlinks skipped: %s; exact target text remains in project-files.jsonl.gz%s." %
                  (len(self.skipped_links), " and cache/skipped-symlinks.jsonl"
                   if not self.args.verify_only else ""), flush=True)
            print("--restore-symlinks recreates only safe relative links within --root; "
                  "external/absolute links are never created.", flush=True)
        print(json.dumps(dict(status="verified" if self.args.verify_only else "restored",
                              scope=self.args.scope, root=str(self.root), **self.counts),
                         ensure_ascii=False, sort_keys=True), flush=True)

    def close(self):
        if self.zip_handle is not None:
            self.zip_handle.close()
        if not self.completed:
            for directory, mode in sorted(self.original_directory_modes.items(),
                                          key=lambda item: len(item[0].parts), reverse=True):
                if directory.is_dir() and not directory.is_symlink():
                    directory.chmod(mode)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=SCOPES, default="final",
                        help="final: desktop + current 285-file delivery + final docs; history: old root; all: both")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="destination directory (default: this repository)")
    parser.add_argument("--cache", type=Path,
                        help="download cache; verified assets are reused (default: ROOT/.restore-cache)")
    parser.add_argument("--manifest-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "manifests",
                        help="manifest directory (default: repository/manifests)")
    parser.add_argument("--verify-only", action="store_true",
                        help="check restored bytes/directories without downloading or writing")
    parser.add_argument("--replace-invalid", action="store_true",
                        help="explicitly replace incorrect regular files or cached assets")
    parser.add_argument("--restore-symlinks", action="store_true",
                        help="also recreate safe internal relative symlinks; external links remain metadata only")
    args = parser.parse_args(argv)
    restorer = Restorer(args)
    try:
        restorer.run()
    except (RestoreError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile,
            urllib.error.URLError) as exc:
        print("Restore failed: " + str(exc), file=sys.stderr)
        return 1
    finally:
        restorer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
