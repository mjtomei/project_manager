"""Collect public planning/design collections without a quality-curation filter.

Run: python3 collect.py [--sources SOURCE ...] [--workers 3]
Then: python3 collect.py --index
Requires git, rsync, pdftotext, and beautifulsoup4. Downloads stay in data/.
The known_good label is the user's experimental assumption, not a measured score.
"""

import argparse
import concurrent.futures
import fnmatch
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
LABEL_BASIS = "User-directed working assumption: established public documents are known-good references relative to current LLM drafts for comparable purposes. No manual quality curation."
EXTENSIONS = {".md", ".markdown", ".rst", ".adoc", ".asciidoc", ".txt", ".html"}


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "PMPlanWritingResearch/0.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
            if b"Making sure you're not a bot" in data[:20000] or b"Anubis could not load" in data[:20000]:
                raise RuntimeError("Source returned an access challenge instead of the document")
            temp = path.with_suffix(path.suffix + ".part")
            temp.write_bytes(data)
            temp.replace(path)
            return data
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def page_text(data):
    soup = BeautifulSoup(data, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.find("article") or soup.find("main") or soup.body or soup
    for element in body.select("script, style, nav, header, footer, noscript"):
        element.decompose()
    return title, body.get_text("\n", strip=True)


def record(source, identity, text, url, raw_path, revision=None, title=None):
    sid = source["id"]
    uid = hashlib.sha256((sid + ":" + identity).encode()).hexdigest()[:24]
    text_path = DATA / "text" / sid / (uid + ".txt")
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")
    return {
        "id": uid, "source": sid, "domain": source["domain"],
        "document_kind": source["document_kind"], "identity": identity,
        "title": title or identity, "url": url, "revision": revision,
        "retrieved_at": datetime.fromtimestamp(raw_path.stat().st_mtime, timezone.utc).isoformat(),
        "raw_path": str(raw_path.relative_to(DATA)),
        "text_path": str(text_path.relative_to(DATA)),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "words": len(text.split()), "known_good": True,
        "label_basis": LABEL_BASIS, "split_group": source.get("split_group", sid),
        "license_note": source.get("license_note", "Retain source notices; rights not independently audited."),
    }


def git_source(source):
    checkout = DATA / "checkouts" / source["id"]
    checkout.parent.mkdir(parents=True, exist_ok=True)
    if not (checkout / ".git").exists():
        run(["git", "clone", "--quiet", "--depth=1", "--filter=blob:none", "--no-checkout", source["url"], str(checkout)], timeout=600)
    run(["git", "-C", str(checkout), "sparse-checkout", "set", "--no-cone", "--stdin"], input="\n".join(source["sparse"]) + "\n", timeout=600)
    run(["git", "-C", str(checkout), "checkout", "--quiet"], timeout=600)
    revision = run(["git", "-C", str(checkout), "rev-parse", "HEAD"]).strip()
    paths = run(["git", "-C", str(checkout), "ls-files", "-z"]).split("\0")
    rows = []
    for rel in paths:
        p = checkout / rel
        if not rel or not p.is_file() or p.is_symlink() or p.suffix.lower() not in EXTENSIONS:
            continue
        if not any(fnmatch.fnmatch(rel, pattern) for pattern in source["include"]):
            continue
        url = source.get("browse", source["url"].removesuffix(".git")) + "/blob/" + revision + "/" + rel
        title, text = (page_text(p.read_bytes()) if p.suffix == ".html"
                       else (None, p.read_text(errors="replace")))
        rows.append(record(source, rel, text, url, p, revision, title))
    return rows, []


def rsync_source(source):
    folder = DATA / "raw" / source["id"]
    folder.mkdir(parents=True, exist_ok=True)
    run(["rsync", "-rz", "--timeout=60", "--contimeout=20", source["url"], str(folder) + "/"], timeout=900)
    rows = []
    for p in sorted(folder.rglob("*.txt")):
        if re.fullmatch(r"rfc\d+\.txt", p.name):
            rows.append(record(source, p.name, p.read_text(errors="replace"), "https://www.rfc-editor.org/rfc/" + p.name, p))
    return rows, []


def collect_web_document(source, url, depth=0):
    if depth > 5:
        raise RuntimeError("Too many document redirects")
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    raw = DATA / "raw" / source["id"] / (key + ".raw")
    data = fetch(url, raw)
    if data.startswith(b"%PDF"):
        out = raw.with_suffix(".txt")
        run(["pdftotext", "-layout", str(raw), str(out)], timeout=180)
        text = out.read_text(errors="replace")
        title = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    else:
        soup = BeautifulSoup(data, "html.parser")
        refresh = soup.find("meta", attrs={"http-equiv": re.compile("^refresh$", re.I)})
        if refresh:
            match = re.search(r"url\s*=\s*(.+)", refresh.get("content", ""), re.I)
            if match:
                target = urllib.parse.urljoin(url, match.group(1).strip(" \"'"))
                if target.startswith(("https://", "http://")):
                    row = collect_web_document(source, target, depth + 1)
                    row["discovered_from_url"] = url
                    return row
        if source.get("ojs_pdf"):
            frame = soup.select_one('iframe[src], embed[src], meta[name="citation_pdf_url"]')
            if frame:
                target = frame.get("src") or frame.get("content")
                if target:
                    return collect_web_document({**source, "ojs_pdf": False}, urllib.parse.urljoin(url, target), depth + 1)
            for a in soup.select("a[href]"):
                if "/download/" in a["href"]:
                    return collect_web_document({**source, "ojs_pdf": False}, urllib.parse.urljoin(url, a["href"]), depth + 1)
        title, text = page_text(data)
        if source.get("text_selector"):
            selected = soup.select_one(source["text_selector"])
            if selected:
                text = selected.get_text("\n", strip=True)
    if not text.strip():
        raise RuntimeError("No extractable text; original retained")
    return record(source, url, text, url, raw, title=title)


def web_source(source):
    urls = set(source.get("urls", []))
    if source.get("index"):
        index_path = DATA / "raw" / source["id"] / "index.html"
        data = fetch(source["index"], index_path)
        soup = BeautifulSoup(data, "html.parser")
        if source.get("index_selector"):
            soup = soup.select_one(source["index_selector"]) or soup
        if source.get("index_start_heading"):
            active = False
            anchors = []
            for element in soup.find_all(["h2", "a"]):
                if element.name == "h2":
                    heading = element.get_text(" ", strip=True)
                    if source["index_start_heading"] in heading:
                        active = True
                    elif active and source.get("index_end_heading", "\0") in heading:
                        break
                if active and element.name == "a" and element.get("href"):
                    anchors.append(element)
        else:
            anchors = soup.select("a[href]")
        for a in anchors:
            url = urllib.parse.urljoin(source["index"], a["href"]).split("#")[0]
            if re.search(source.get("link_pattern", ".*"), url):
                urls.add(url)
        if source.get("oxide_index"):
            for number in re.findall(r"/rfd/(\d{4})", data.decode(errors="replace")):
                urls.add("https://rfd.shared.oxide.computer/rfd/" + number)
    rows, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(collect_web_document, source, u): u for u in sorted(urls)}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                errors.append({"url": url, "error": str(exc)})
    if not urls:
        errors.append({"error": "Index discovery yielded no documents"})
    return rows, errors


def collect(source):
    sid = source["id"]
    print(json.dumps({"source": sid, "status": "starting"}), flush=True)
    try:
        rows, errors = {"git": git_source, "web": web_source, "rsync": rsync_source}[source["kind"]](source)
    except Exception as exc:
        rows, errors = [], [{"error": str(exc), "detail": getattr(exc, "stderr", "")[-2000:]}]
    folder = DATA / "manifests"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (sid + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in sorted(rows, key=lambda x: x["id"])))
    status = {"source": sid, "documents": len(rows), "words": sum(r["words"] for r in rows), "errors": errors}
    (folder / (sid + ".status.json")).write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status), flush=True)


def build_index():
    rows, statuses = [], []
    for path in sorted((DATA / "manifests").glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines())
    for path in sorted((DATA / "manifests").glob("*.status.json")):
        statuses.append(json.loads(path.read_text()))
    canonical = {}
    for r in rows:
        r["eligible_for_text_evaluation"] = r["words"] > 0
        r["duplicate_group"] = r["sha256"]
        r["canonical_id"] = canonical.setdefault(r["sha256"], r["id"])
    (DATA / "corpus.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    report = {"documents": len(rows), "unique_texts": len(canonical), "words": sum(r["words"] for r in rows),
              "nonempty_documents": sum(r["eligible_for_text_evaluation"] for r in rows),
              "empty_texts": sum(not r["eligible_for_text_evaluation"] for r in rows),
              "unique_nonempty_texts": len({r["sha256"] for r in rows if r["eligible_for_text_evaluation"]}),
              "by_domain": dict(Counter(r["domain"] for r in rows)), "sources": statuses,
              "known_good_label_basis": LABEL_BASIS,
              "split_note": "No train/test assignment yet. Keep duplicate groups, revisions and shared project provenance together when splitting.",
              "extraction_note": "Raw sources retained. PDF text does not preserve all diagrams, equations or table structure.",
              "model_evaluations_run": 0, "training_runs": 0}
    (DATA / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k:v for k,v in report.items() if k != "sources"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="*")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--index", action="store_true")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if args.index:
        build_index()
    else:
        sources = json.loads((HERE / "sources.json").read_text())["sources"]
        if args.sources:
            unknown = set(args.sources) - {s["id"] for s in sources}
            if unknown:
                parser.error("Unknown sources: " + ", ".join(sorted(unknown)))
            sources = [s for s in sources if s["id"] in args.sources]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(collect, sources))
