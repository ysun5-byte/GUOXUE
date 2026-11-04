#!/usr/bin/env python3
"""Content-deduplicated, resumable GitHub Release archive (Python stdlib only).

`plan` is offline/read-only toward sources and GitHub. `run` uploads ONLY to an
already-created draft release; it never creates/publishes releases, changes refs,
overwrites remote assets, or removes sources. `simulate` uses a marked local
directory, with file:// URLs, and performs no network activity.

The local plan DB, spool, upload state, CLI configuration, and source inventory
contain machine-specific paths and MUST NOT be committed. Only the final public
manifests belong in Git. Keep the CLI auth directory outside all source scopes.
"""
import argparse
import contextlib
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import zipfile

MIB = 1024 * 1024
GIB = 1024 * MIB
DEFAULT_REPO = "ysun5-byte/GUOXUE"
DEFAULT_TAG = "part1-complete-2026-11-04"
BLOCK = 4 * MIB
PRECOMPRESSED_SUFFIXES = {".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z", ".rar",
                         ".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".pdf",
                         ".pptx", ".xlsx", ".docx", ".mp3", ".mp4", ".mov", ".woff", ".woff2"}
SECRET_PATTERNS = (
    ("github_classic_token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("github_fine_grained_token", re.compile(rb"github_pat_[A-Za-z0-9_]{70,255}\b")),
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_project_key", re.compile(rb"\bsk-proj-[A-Za-z0-9_-]{48,255}\b")),
)


class ArchiveError(RuntimeError):
    pass


class RemoteAssetError(ArchiveError):
    """A deterministic remote conflict requiring review, never a blind retry."""
    def __init__(self, message, reason, asset):
        self.reason = reason
        state = asset.get("state")
        self.remote_state = state if state in ("uploaded", "starter") else "unknown"
        identifier = asset.get("id")
        self.asset_id = (identifier if isinstance(identifier, int) or
                         isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,200}", identifier)
                         else "unknown")
        self.actual_bytes = asset.get("size") if isinstance(asset.get("size"), int) else None
        super().__init__(message + "; state=" + self.remote_state + ", asset_id=" + str(self.asset_id) +
                         "; no overwrite or deletion attempted")


def require_uploaded_asset(asset):
    if asset.get("state") != "uploaded":
        raise RemoteAssetError("Remote asset is not completely uploaded", "remote_asset_state_not_uploaded", asset)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def digest_file(path):
    h = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK), b""):
            h.update(block)
            size += len(block)
    return size, h.hexdigest()


def jsonl_gzip(path, records):
    """Deterministic gzip, atomic replacement, without accumulating all rows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            for record in records:
                compressed.write((canonical(record) + "\n").encode("utf-8"))
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temp, path)


def connect_readonly(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def meta_get(conn, key):
    row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    if row is None:
        raise ArchiveError("Missing plan metadata: " + key)
    return json.loads(row[0])


def safe_repo_path(value):
    if not value or value.startswith("/") or "\\" in value or any(x in ("", ".", "..") for x in value.split("/")):
        raise ArchiveError("Unsafe manifest path: " + repr(value))
    return value


def file_records(inventory):
    for row in inventory.execute("SELECT path,scope,relative_path,kind,bytes,mode,sha256,link_target FROM paths ORDER BY path"):
        record = dict(row)
        safe_repo_path(record["path"])
        if record["kind"] not in ("file", "symlink"):
            raise ArchiveError("Unsupported inventory kind: " + record["kind"])
        if record["link_target"] is None:
            del record["link_target"]
        yield record


def plan_archive(args):
    if not 0 < args.part_limit <= GIB:
        raise ArchiveError("part-limit must be between 1 byte and 1 GiB")
    if not 0 < args.pack_limit <= 512 * MIB:
        raise ArchiveError("pack-limit must be between 1 byte and 512 MiB")
    if args.small_limit < 0:
        raise ArchiveError("small-limit must be nonnegative")
    inventory_path = Path(args.inventory).resolve()
    plan_path = Path(args.plan).resolve()
    manifest_dir = Path(args.manifest_dir).resolve()
    if plan_path.exists():
        raise ArchiveError("Plan already exists; reuse it, or choose a new plan path")
    with contextlib.closing(connect_readonly(inventory_path)) as inv:
        row = inv.execute("SELECT value FROM metadata WHERE key='summary'").fetchone()
        if row is None or json.loads(row[0]).get("status") != "complete":
            raise ArchiveError("Inventory is incomplete; no archive was planned")
        summary = json.loads(row[0])
        manifest_dir.mkdir(parents=True, exist_ok=True)
        files_path = manifest_dir / "project-files.jsonl.gz"
        jsonl_gzip(files_path, file_records(inv))
        _, files_sha = digest_file(files_path)
        settings = {"small_limit": args.small_limit, "pack_limit": args.pack_limit,
                    "part_limit": args.part_limit, "compression": args.compression}
        identity = {"summary": summary, "project_files_sha256": files_sha, "settings": settings}
        plan_id = hashlib.sha256(canonical(identity).encode()).hexdigest()
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        temp = plan_path.with_name(plan_path.name + ".tmp")
        if temp.exists():
            raise ArchiveError("Unfinished plan exists: " + str(temp))
        db = sqlite3.connect(temp)
        try:
            db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE objects(sha256 TEXT PRIMARY KEY,bytes INTEGER NOT NULL,
                source_path TEXT NOT NULL,kind TEXT NOT NULL,link_target TEXT,storage TEXT NOT NULL);
            CREATE TABLE assets(seq INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL,uncompressed_bytes INTEGER NOT NULL,bytes INTEGER,sha256 TEXT);
            CREATE TABLE members(object_sha TEXT PRIMARY KEY,asset TEXT NOT NULL,member TEXT NOT NULL);
            CREATE INDEX members_asset ON members(asset);
            CREATE TABLE parts(object_sha TEXT NOT NULL,part_index INTEGER NOT NULL,
                asset TEXT UNIQUE NOT NULL,offset INTEGER NOT NULL,bytes INTEGER NOT NULL,sha256 TEXT,
                PRIMARY KEY(object_sha,part_index));
            CREATE TABLE findings(object_sha TEXT NOT NULL,category TEXT NOT NULL,byte_offset INTEGER NOT NULL,
                PRIMARY KEY(object_sha,category,byte_offset));
            CREATE TABLE checked_objects(object_sha TEXT PRIMARY KEY);
            """)
            values = {"schema_version": 1, "plan_id": plan_id, "inventory": str(inventory_path),
                      "manifest_dir": str(manifest_dir), "settings": settings, "summary": summary,
                      "project_files_sha256": files_sha}
            db.executemany("INSERT INTO metadata VALUES(?,?)", [(k, canonical(v)) for k, v in values.items()])
            # A final delivery volume is preserved as raw ordered parts even if small.
            formal = {row[0] for row in inv.execute("SELECT DISTINCT sha256 FROM paths WHERE scope='final_view' AND relative_path LIKE 'volumes/%'")}
            seq = pack_number = 0
            current_pack = None
            pack_bytes = 0
            counts = {"unique_objects": 0, "unique_bytes": 0, "pack_assets": 0, "part_assets": 0}
            for obj in inv.execute("SELECT sha256,bytes,source_path,kind FROM objects ORDER BY sha256"):
                sha, size, source, kind = obj
                if not re.fullmatch(r"[0-9a-f]{64}", sha) or size < 0:
                    raise ArchiveError("Invalid inventory object")
                link_target = None
                if kind == "symlink":
                    found = inv.execute("SELECT link_target FROM paths WHERE sha256=? AND kind='symlink' LIMIT 1", (sha,)).fetchone()
                    if found is None:
                        raise ArchiveError("Symlink object has no target metadata")
                    link_target = found[0]
                use_parts = size > args.small_limit or size > args.pack_limit or sha in formal
                storage = "parts" if use_parts else "zip_member"
                db.execute("INSERT INTO objects VALUES(?,?,?,?,?,?)", (sha, size, source, kind, link_target, storage))
                counts["unique_objects"] += 1
                counts["unique_bytes"] += size
                if use_parts:
                    # Empty volumes still need a content-bearing asset for completeness.
                    for index, offset in enumerate(range(0, max(size, 1), args.part_limit), 1):
                        amount = min(args.part_limit, size - offset)
                        name = "archive-object-" + sha + "-part-" + format(index, "05d") + ".bin"
                        seq += 1
                        db.execute("INSERT INTO assets(seq,name,kind,uncompressed_bytes) VALUES(?,?,?,?)", (seq, name, "part", amount))
                        db.execute("INSERT INTO parts VALUES(?,?,?,?,?,NULL)", (sha, index, name, offset, amount))
                        counts["part_assets"] += 1
                else:
                    if current_pack is None or pack_bytes + size > args.pack_limit:
                        seq += 1
                        pack_number += 1
                        current_pack = "archive-pack-" + format(pack_number, "06d") + ".zip"
                        pack_bytes = 0
                        db.execute("INSERT INTO assets(seq,name,kind,uncompressed_bytes) VALUES(?,?,?,0)", (seq, current_pack, "pack"))
                        counts["pack_assets"] += 1
                    member = "objects/" + sha
                    db.execute("INSERT INTO members VALUES(?,?,?)", (sha, current_pack, member))
                    db.execute("UPDATE assets SET uncompressed_bytes=uncompressed_bytes+? WHERE name=?", (size, current_pack))
                    pack_bytes += size
            missing = inv.execute("SELECT count(*) FROM paths WHERE sha256 NOT IN(SELECT sha256 FROM objects)").fetchone()[0]
            if missing:
                raise ArchiveError("Inventory references missing objects")
            db.execute("INSERT INTO metadata VALUES(?,?)", ("counts", canonical(counts)))
            db.commit()
        finally:
            db.close()
        os.replace(temp, plan_path)
    output = {"stage": "planned", "plan_id": plan_id, **counts,
              "plan": str(plan_path), "manifest_dir": str(manifest_dir),
              "network_activity": False, "sources_modified": False}
    atomic_json(plan_path.with_name("archive_plan_summary.json"), output)
    print(canonical(output), flush=True)
    return output


@contextlib.contextmanager
def object_stream(obj, expected_fingerprint=None):
    """Never dereference an archived symlink to a local/external dependency."""
    path = Path(obj["source_path"])
    before = path.lstat()
    before_fingerprint = source_fingerprint(before)
    if expected_fingerprint is not None and before_fingerprint != expected_fingerprint:
        raise ArchiveError("Source changed since its full SHA check: " + str(path))
    if obj["kind"] == "symlink":
        target = os.readlink(path)
        if target != obj["link_target"]:
            raise ArchiveError("Symlink changed since inventory: " + str(path))
        with io.BytesIO(os.fsencode(target)) as stream:
            yield stream, before_fingerprint
    else:
        if not path.is_file() or path.is_symlink():
            raise ArchiveError("Source kind changed: " + str(path))
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if source_fingerprint(opened) != before_fingerprint:
                raise ArchiveError("Source changed while opening: " + str(path))
            yield stream, before_fingerprint
            after_fd = os.fstat(stream.fileno())
            if source_fingerprint(after_fd) != before_fingerprint:
                raise ArchiveError("Source changed while reading: " + str(path))
    after = path.lstat()
    if source_fingerprint(after) != before_fingerprint:
        raise ArchiveError("Source changed while reading: " + str(path))


def source_fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class Scanner:
    def __init__(self):
        self.tail = b""
        self.offset = 0
        self.findings = set()

    def feed(self, block):
        candidate = self.tail + block
        for category, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(candidate):
                self.findings.add((category, self.offset - len(self.tail) + match.start()))
        self.offset += len(block)
        self.tail = candidate[-512:]


def record_findings(db, obj, scanner):
    if not scanner.findings:
        return
    db.executemany("INSERT OR IGNORE INTO findings VALUES(?,?,?)",
                   [(obj["sha256"], category, offset) for category, offset in sorted(scanner.findings)])
    db.commit()
    report_findings(db)
    raise ArchiveError("Credential-pattern finding; the current asset was not uploaded. Review the local findings report; original files were not changed")


def report_findings(db):
    inv_path = meta_get(db, "inventory")
    reports = []
    with contextlib.closing(connect_readonly(inv_path)) as inv:
        for sha, category, offset in db.execute("SELECT object_sha,category,byte_offset FROM findings ORDER BY object_sha,category,byte_offset"):
            aliases = [r[0] for r in inv.execute("SELECT path FROM paths WHERE sha256=? ORDER BY path", (sha,))]
            reports.append({"sha256": sha, "category": category, "byte_offset": offset, "paths": aliases})
    # Never include matching bytes, tokens, private keys, or CLI environment.
    atomic_json(Path(db.execute("PRAGMA database_list").fetchone()[2]).parent / "archive_secret_findings.json", reports)


def copy_verified_object(db, obj, destination=None):
    h = hashlib.sha256()
    total = 0
    scanner = Scanner()
    with object_stream(obj) as (source, fingerprint):
        for block in iter(lambda: source.read(BLOCK), b""):
            h.update(block)
            scanner.feed(block)
            total += len(block)
            if destination is not None:
                destination.write(block)
    if total != obj["bytes"] or h.hexdigest() != obj["sha256"]:
        raise ArchiveError("Source no longer matches inventory: " + obj["source_path"])
    record_findings(db, obj, scanner)
    db.execute("INSERT OR IGNORE INTO checked_objects VALUES(?)", (obj["sha256"],))
    return fingerprint


def build_asset(db, asset, spool, checked_large):
    """Build exactly one script-owned asset, bounded by the planned part/pack size."""
    name = asset["name"]
    if Path(name).name != name or not name.startswith("archive-"):
        raise ArchiveError("Unsafe asset name")
    destination = spool / name
    pending = spool / (name + ".building")
    if pending.exists():
        pending.unlink()  # Marker-checked private spool; always script-owned.
    if destination.exists() and asset["sha256"]:
        size, sha = digest_file(destination)
        if size == asset["bytes"] and sha == asset["sha256"]:
            return destination
        destination.unlink()
    if asset["kind"] == "pack":
        policy = meta_get(db, "settings")["compression"]
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            rows = db.execute("SELECT o.*,m.member FROM objects o JOIN members m ON m.object_sha=o.sha256 WHERE m.asset=? ORDER BY o.sha256", (name,)).fetchall()
            for obj in rows:
                entry = zipfile.ZipInfo(obj["member"], date_time=(1980, 1, 1, 0, 0, 0))
                compressed_source = Path(obj["source_path"]).suffix.lower() in PRECOMPRESSED_SUFFIXES
                entry.compress_type = (zipfile.ZIP_STORED if policy == "stored" or (policy == "auto" and compressed_source)
                                       else zipfile.ZIP_DEFLATED)
                entry._compresslevel = 1
                entry.create_system = 3
                entry.external_attr = 0o100600 << 16
                with archive.open(entry, "w", force_zip64=True) as member:
                    copy_verified_object(db, obj, member)
        # Independently read ZIP members and verify extracted content before upload.
        with zipfile.ZipFile(pending, "r") as archive:
            if archive.namelist() != [r["member"] for r in rows]:
                raise ArchiveError("ZIP has unexpected members")
            for obj in rows:
                h = hashlib.sha256()
                size = 0
                with archive.open(obj["member"]) as member:
                    for block in iter(lambda: member.read(BLOCK), b""):
                        h.update(block)
                        size += len(block)
                if size != obj["bytes"] or h.hexdigest() != obj["sha256"]:
                    raise ArchiveError("ZIP member verification failed: " + obj["member"])
    else:
        part = db.execute("SELECT * FROM parts WHERE asset=?", (name,)).fetchone()
        obj = db.execute("SELECT * FROM objects WHERE sha256=?", (part["object_sha"],)).fetchone()
        if obj["sha256"] not in checked_large:
            # Preserve the exact fstat identity from the verified file descriptor.
            checked_large[obj["sha256"]] = copy_verified_object(db, obj)
        with object_stream(obj, checked_large[obj["sha256"]]) as (source, _), pending.open("wb") as output:
            source.seek(part["offset"])
            remaining = part["bytes"]
            while remaining:
                block = source.read(min(BLOCK, remaining))
                if not block:
                    raise ArchiveError("Unexpected end of source")
                output.write(block)
                remaining -= len(block)
        if pending.stat().st_size != part["bytes"]:
            raise ArchiveError("Part size mismatch")
    size, sha = digest_file(pending)
    if asset["sha256"] and (sha != asset["sha256"] or size != asset["bytes"]):
        raise ArchiveError("Regenerated asset differs from checkpoint: " + name)
    os.replace(pending, destination)
    db.execute("UPDATE assets SET bytes=?,sha256=? WHERE name=?", (size, sha, name))
    if asset["kind"] == "part":
        db.execute("UPDATE parts SET sha256=? WHERE asset=?", (sha, name))
    db.commit()
    return destination


class LocalRemote:
    """Test transport: marked local directory only, never GitHub."""
    def __init__(self, directory, repo, tag, release_id):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        marker = self.directory / ".guoxue-simulated-release.json"
        identity = {"repo": repo, "tag": tag, "release_id": release_id, "simulation": True}
        if marker.exists():
            if json.loads(marker.read_text()) != identity:
                raise ArchiveError("Simulation directory belongs to another archive")
        elif any(self.directory.iterdir()):
            raise ArchiveError("Simulation destination is not empty or script-owned")
        else:
            atomic_json(marker, identity)
        self.upload_count = 0

    def find(self, name):
        path = self.directory / name
        if not path.exists():
            return None
        size, sha = digest_file(path)
        return {"name": name, "size": size, "digest": "sha256:" + sha,
                "id": name, "state": "uploaded", "browser_download_url": path.as_uri()}

    def upload(self, path):
        dest = self.directory / path.name
        # Exclusive creation; no clobber even when rerun after interruption.
        with path.open("rb") as source, dest.open("xb") as output:
            shutil.copyfileobj(source, output, BLOCK)
        self.upload_count += 1
        return self.find(path.name)

    def verify(self, asset, expected_size, expected_sha):
        require_uploaded_asset(asset)
        if asset["size"] != expected_size or asset.get("digest") != "sha256:" + expected_sha:
            raise RemoteAssetError("Existing simulation asset differs: " + asset["name"], "remote_asset_content_mismatch", asset)


class GitHubRemote:
    def __init__(self, setup_file, repo, tag, release_id):
        setup = json.loads(Path(setup_file).read_text())
        # Read path metadata only. Never read token/config content or print env.
        self.binary = setup.get("binary") or setup.get("binary_path") or setup.get("gh_binary")
        self.auth_dir = setup.get("auth_config_directory")
        if not self.binary or not self.auth_dir:
            raise ArchiveError("CLI setup needs binary and auth_config_directory paths")
        self.env = dict(os.environ, GH_CONFIG_DIR=self.auth_dir, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
        self.repo, self.tag, self.release_id = repo, tag, release_id
        self.validate_release()
        self.cache = None

    def validate_release(self):
        release = self.api("repos/" + self.repo + "/releases/" + str(self.release_id))
        if release.get("id") != self.release_id or release.get("tag_name") != self.tag or release.get("draft") is not True:
            raise ArchiveError("Upload target is not the exact expected existing draft release")

    def command(self, arguments):
        result = subprocess.run([self.binary] + arguments, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            # Do not echo CLI diagnostics: they can contain request URLs or configuration.
            raise ArchiveError("GitHub CLI operation failed (exit " + str(result.returncode) + "); checkpoint retained")
        return result.stdout

    def api(self, endpoint, extra=()):
        try:
            return json.loads(self.command(["api", endpoint] + list(extra)))
        except json.JSONDecodeError as exc:
            raise ArchiveError("GitHub returned invalid JSON") from exc

    def refresh(self):
        pages = self.api("repos/" + self.repo + "/releases/" + str(self.release_id) + "/assets?per_page=100", ("--paginate", "--slurp"))
        self.cache = {}
        for page in pages:
            for asset in page:
                if asset["name"] in self.cache:
                    raise ArchiveError("Release contains duplicate asset names")
                self.cache[asset["name"]] = asset

    def find(self, name):
        if self.cache is None:
            self.refresh()
        return self.cache.get(name)

    def upload(self, path):
        self.validate_release()
        try:
            # Target the verified release ID directly, rather than resolving its
            # tag again. Asset names are script-generated ASCII without query syntax.
            endpoint = "https://uploads.github.com/repos/" + self.repo + "/releases/" + str(self.release_id) + "/assets?name=" + path.name
            self.api(endpoint, ("--method", "POST", "-H", "Content-Type: application/octet-stream", "--input", str(path)))
        finally:
            self.cache = None  # Handles an accepted upload followed by connection loss.
        return self.find(path.name)

    def verify(self, asset, expected_size, expected_sha):
        require_uploaded_asset(asset)
        if asset.get("size") != expected_size:
            raise RemoteAssetError("Remote asset size differs: " + asset["name"], "remote_asset_size_mismatch", asset)
        digest = asset.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            if digest != "sha256:" + expected_sha:
                raise RemoteAssetError("Remote asset SHA-256 differs: " + asset["name"], "remote_asset_sha256_mismatch", asset)
            return
        # Older GitHub responses have no digest: authenticated download is streamed
        # through gh; no token is obtained, logged, or embedded in a URL.
        endpoint = "repos/" + self.repo + "/releases/assets/" + str(asset["id"])
        proc = subprocess.Popen([self.binary, "api", endpoint, "-H", "Accept: application/octet-stream"],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        h = hashlib.sha256()
        size = 0
        try:
            for block in iter(lambda: proc.stdout.read(BLOCK), b""):
                size += len(block)
                h.update(block)
        finally:
            proc.stdout.close()
        code = proc.wait()
        if code:
            raise ArchiveError("Remote asset streamed SHA-256 verification failed: " + asset["name"])
        if size != expected_size or h.hexdigest() != expected_sha:
            raise RemoteAssetError("Remote asset streamed SHA-256 verification failed: " + asset["name"],
                                   "remote_asset_download_sha256_mismatch", asset)


def verify_with_receipt(remote, asset, expected_size, expected_sha, state, state_path, name):
    try:
        remote.verify(asset, expected_size, expected_sha)
    except RemoteAssetError as exc:
        receipt = {"schema_version": 1, "repo": state["repo"], "tag": state["tag"],
                   "release_id": state["release_id"], "plan_id": state["plan_id"],
                   "simulation": state["simulation"], "asset": name, "asset_id": exc.asset_id,
                   "remote_state": exc.remote_state, "actual_bytes": exc.actual_bytes,
                   "expected_bytes": expected_size, "expected_sha256": expected_sha,
                   "reason": exc.reason, "time_unix": time.time(),
                   "remote_asset_deleted": False, "remote_asset_overwritten": False}
        checkpoint = state["assets"].setdefault(name, {"expected_bytes": expected_size, "expected_sha256": expected_sha})
        checkpoint.update({"verified": False, "last_failure": receipt})
        state["complete"] = False
        atomic_json(state_path, state)
        receipt_path = state_path.with_name("upload_failures.jsonl")
        with receipt_path.open("a", encoding="utf-8") as output:
            output.write(canonical(receipt) + "\n")
            output.flush()
            os.fsync(output.fileno())
        raise


def refresh_verified_checkpoint(checkpoint, asset, expected_sha):
    checkpoint.update({"actual_bytes": asset["size"], "actual_sha256": expected_sha,
                       "verified": True, "asset_id": asset["id"],
                       "browser_download_url": asset["browser_download_url"]})
    checkpoint.pop("last_failure", None)


def owned_spool(directory, plan_id):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".guoxue-archive-spool.json"
    expected = {"plan_id": plan_id, "purpose": "generated archive assets only"}
    if marker.exists():
        if json.loads(marker.read_text()) != expected:
            raise ArchiveError("Spool belongs to another archive plan")
    elif any(directory.iterdir()):
        raise ArchiveError("Spool is not empty or script-owned")
    else:
        atomic_json(marker, expected)
    # The only disposable files are names this script generates in its own spool.
    for item in directory.iterdir():
        if item.is_file() and re.fullmatch(r"archive-(?:pack-\d{6}\.zip|object-[0-9a-f]{64}-part-\d{5}\.bin)\.building", item.name):
            item.unlink()
    return directory


def object_records(db):
    for obj in db.execute("SELECT sha256,bytes,storage FROM objects ORDER BY sha256"):
        record = dict(obj)
        if obj["storage"] == "zip_member":
            row = db.execute("SELECT asset,member FROM members WHERE object_sha=?", (obj["sha256"],)).fetchone()
            record.update(dict(row))
        else:
            parts = [dict(r) for r in db.execute("SELECT asset,bytes,sha256 FROM parts WHERE object_sha=? ORDER BY part_index", (obj["sha256"],))]
            if not parts or any(not p["sha256"] for p in parts) or sum(p["bytes"] for p in parts) != obj["bytes"]:
                raise ArchiveError("Object has incomplete parts")
            record["parts"] = parts
        yield record


def export_manifests(db, state):
    directory = Path(meta_get(db, "manifest_dir"))
    if digest_file(directory / "project-files.jsonl.gz")[1] != meta_get(db, "project_files_sha256"):
        raise ArchiveError("Project file manifest changed after planning; no final manifests exported")
    missing = [row[0] for row in db.execute("SELECT name FROM assets ORDER BY seq") if not state["assets"].get(row[0], {}).get("verified")]
    if missing:
        raise ArchiveError("Cannot export final manifests with unverified assets")
    if db.execute("SELECT count(*) FROM objects WHERE sha256 NOT IN(SELECT object_sha FROM checked_objects)").fetchone()[0]:
        raise ArchiveError("Cannot export: some unique objects have not passed source SHA and credential-pattern checks")
    jsonl_gzip(directory / "objects.jsonl.gz", object_records(db))
    assets = []
    for row in db.execute("SELECT name,bytes,sha256 FROM assets ORDER BY seq"):
        verified = state["assets"][row["name"]]
        # Draft-release responses can expose an ephemeral untagged-* URL. The
        # public restore manifest must name the final, verified release tag.
        # Retain the observed API URL only in the local upload checkpoint.
        download_url = (verified["browser_download_url"] if state["simulation"] else
                        "https://github.com/" + state["repo"] + "/releases/download/" +
                        quote(state["tag"], safe="") + "/" + quote(row["name"], safe=""))
        assets.append({"name": row["name"], "bytes": row["bytes"], "sha256": row["sha256"],
                       "browser_download_url": download_url, "asset_id": verified["asset_id"]})
    release = {"schema_version": 1, "repo": state["repo"], "tag": state["tag"],
               "release_id": state["release_id"], "assets": assets}
    if state["simulation"]:
        release["simulation"] = True
    atomic_json(directory / "release-assets.json", release)
    return release


def run_archive(args):
    # Two foreground retries must never write the same spool/checkpoint at once.
    lock_path = Path(args.plan).resolve().with_suffix(".upload.lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArchiveError("This archive plan is already being processed; wait for that foreground process to finish") from exc
        return run_archive_locked(args)


def run_archive_locked(args):
    plan_path = Path(args.plan).resolve()
    db = sqlite3.connect(plan_path)
    db.row_factory = sqlite3.Row
    try:
        plan_id = meta_get(db, "plan_id")
        state_path = Path(args.state).resolve()
        simulation = args.command == "simulate"
        expected = {"schema_version": 1, "repo": args.repo, "tag": args.tag,
                    "release_id": args.release_id, "plan_id": plan_id, "simulation": simulation}
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if any(state.get(key) != value for key, value in expected.items()):
                raise ArchiveError("Upload checkpoint identity differs from requested destination")
        else:
            state = dict(expected, assets={}, complete=False)
        # A failed revalidation must not leave a previous successful status behind.
        state["complete"] = False
        atomic_json(state_path, state)
        findings = db.execute("SELECT count(*) FROM findings").fetchone()[0]
        if findings:
            report_findings(db)
            raise ArchiveError("Unresolved credential-pattern findings; no upload attempted")
        spool = owned_spool(args.spool, plan_id)
        remote = (LocalRemote(args.simulate_dir, args.repo, args.tag, args.release_id) if simulation
                  else GitHubRemote(args.cli_setup, args.repo, args.tag, args.release_id))
        checked_large = {}
        completed_now = 0
        assets = db.execute("SELECT * FROM assets ORDER BY seq").fetchall()
        for number, asset in enumerate(assets, 1):
            name = asset["name"]
            checkpoint = state["assets"].get(name)
            if checkpoint and checkpoint.get("verified"):
                if checkpoint.get("expected_sha256") != asset["sha256"] or checkpoint.get("expected_bytes") != asset["bytes"]:
                    raise ArchiveError("Verified checkpoint and plan disagree: " + name)
                existing = remote.find(name)
                if existing is None:
                    raise ArchiveError("Previously verified remote asset is missing: " + name)
                verify_with_receipt(remote, existing, asset["bytes"], asset["sha256"], state, state_path, name)
                # Same verified bytes can belong to a newly created remote ID.
                refresh_verified_checkpoint(checkpoint, existing, asset["sha256"])
                atomic_json(state_path, state)
                cached = spool / name
                if cached.exists() and not args.keep_spool:
                    cached.unlink()
                continue
            path = build_asset(db, asset, spool, checked_large)
            size, sha = digest_file(path)
            state["assets"][name] = {"expected_bytes": size, "expected_sha256": sha, "verified": False}
            atomic_json(state_path, state)
            verified_asset = None
            for attempt in range(args.retries + 1):
                try:
                    existing = remote.find(name)
                    verified_asset = existing if existing is not None else remote.upload(path)
                    if verified_asset is None:
                        raise ArchiveError("Uploaded asset was not found in its release")
                    verify_with_receipt(remote, verified_asset, size, sha, state, state_path, name)
                    break
                except RemoteAssetError:
                    raise  # starter placeholders and mismatches require explicit review.
                except (ArchiveError, OSError) as exc:
                    # A failed HTTP upload (notably a 502) can leave a starter
                    # placeholder. Probe once before retry/exit, even when no
                    # retries remain, so its exact ID/state has a durable receipt.
                    try:
                        possible_placeholder = remote.find(name)
                        if possible_placeholder is not None and possible_placeholder.get("state") != "uploaded":
                            verify_with_receipt(remote, possible_placeholder, size, sha, state, state_path, name)
                    except RemoteAssetError:
                        raise
                    except (ArchiveError, OSError):
                        pass  # Preserve the original transport failure/checkpoint.
                    if attempt >= args.retries:
                        raise
                    print(canonical({"stage": "retry", "asset": name, "attempt": attempt + 1,
                                     "checkpoint_retained": True}), flush=True)
                    time.sleep(min(2 ** attempt, 20))
            # No success state is written before exact size and SHA verification.
            refresh_verified_checkpoint(state["assets"][name], verified_asset, sha)
            atomic_json(state_path, state)
            completed_now += 1
            print(canonical({"stage": "verified", "asset": name, "bytes": size,
                             "progress": [number, len(assets)], "simulation": simulation}), flush=True)
            if not args.keep_spool:
                path.unlink()
            if args.stop_after and completed_now >= args.stop_after:
                raise ArchiveError("Requested checkpoint stop after verified assets; rerun the same command to resume")
        release = export_manifests(db, state)
        state["complete"] = True
        atomic_json(state_path, state)
        output = {"stage": "complete", "assets": len(release["assets"]), "simulation": simulation,
                  "release_published": False, "sources_modified": False,
                  "manifest_dir": meta_get(db, "manifest_dir")}
        if simulation:
            output["new_simulated_uploads"] = remote.upload_count
        print(canonical(output), flush=True)
        return output
    finally:
        db.close()


def parser():
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="offline plan; requires complete inventory")
    plan.add_argument("--inventory", required=True)
    plan.add_argument("--plan", required=True)
    plan.add_argument("--manifest-dir", required=True)
    plan.add_argument("--small-limit", type=int, default=48 * MIB)
    plan.add_argument("--pack-limit", type=int, default=512 * MIB)
    plan.add_argument("--part-limit", type=int, default=GIB)
    plan.add_argument("--compression", choices=("auto", "stored", "deflate"), default="auto",
                      help="default auto: deflate level 1; store already-compressed file types")
    plan.set_defaults(func=plan_archive)
    for name in ("run", "simulate"):
        command = commands.add_parser(name, help="upload to an existing draft release" if name == "run" else "local fixture transport; no network")
        command.add_argument("--plan", required=True)
        command.add_argument("--state", required=True)
        command.add_argument("--spool", required=True)
        command.add_argument("--repo", default=DEFAULT_REPO)
        command.add_argument("--tag", default=DEFAULT_TAG)
        command.add_argument("--release-id", required=True, type=int)
        command.add_argument("--retries", type=int, default=3)
        command.add_argument("--keep-spool", action="store_true")
        command.add_argument("--stop-after", type=int, default=0, help="stop after N new verified assets to test checkpoint resumption")
        if name == "run":
            command.add_argument("--cli-setup", required=True)
        else:
            command.add_argument("--simulate-dir", required=True)
        command.set_defaults(func=run_archive)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if hasattr(args, "retries") and args.retries < 0:
        raise ArchiveError("Retries must be nonnegative")
    return args.func(args)


if __name__ == "__main__":
    try:
        main()
    except (ArchiveError, OSError, sqlite3.Error, ValueError, zipfile.BadZipFile) as exc:
        print("archive stopped: " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
