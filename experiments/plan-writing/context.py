"""Collect the context that states each document's purpose.

Run after collect.py: python3 context.py [--sources SOURCE ...]
Writes data/context/<source>.jsonl (one item per line) and
data/context/<source>.status.json. Fetched pages are cached under
data/context/raw/ so reruns are cheap and resumable.

An item is either document-specific (an issue, review thread, metadata
record, index entry, charter milestone or study call naming the document's
group) or a shared process document (a template or process description that
applies to every document of the source). Only opening posts of issues and
threads are kept: they state the request, while later comments review the
finished document. Fields recording decisions taken after writing (status,
resolution, milestones reached) are excluded so context does not reveal
outcomes. cases.py filters every item against the document body before it
enters a brief.

Each item is stamped with when it was written relative to the document
(sources.json `written`); cases.py never uses context written after the
document. data/context/<source>.dates.json records each document's date,
which selects the process-document versions attached to it.
"""

import argparse
import concurrent.futures
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

import docmeta
from collect import DATA, HERE, page_text, run

CTX = DATA / "context"
USER_AGENT = "PMPlanWritingResearch/0.1"
_host_locks = defaultdict(lambda: threading.Semaphore(3))
_host_locks_guard = threading.Lock()


class FetchError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def fetch(url, binary=False, attempts=5):
    """Fetch through the cache; returns (data, retrieved_at). Raises FetchError."""
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    path = CTX / "raw" / urllib.parse.urlsplit(url).netloc / (key + ".raw")
    meta = path.with_suffix(".json")
    if meta.exists():
        info = json.loads(meta.read_text())
        if info.get("status") != 200:  # permanent failures are cached as metadata only
            raise FetchError(f"HTTP {info.get('status')} (cached)")
        if path.exists():
            data = path.read_bytes()
            return (data if binary else data.decode("utf-8", "replace")), info["retrieved_at"]
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    host = urllib.parse.urlsplit(url).netloc
    with _host_locks_guard:  # one semaphore per host even when threads meet it first together
        limit = _host_locks[host]
    for attempt in range(attempts):
        try:
            with limit:
                with urllib.request.urlopen(req, timeout=60) as response:
                    data = response.read()
                    final = response.geturl()
            stamp = now()
            path.write_bytes(data)
            meta.write_text(json.dumps({"url": url, "final_url": final, "status": 200, "retrieved_at": stamp}))
            return (data if binary else data.decode("utf-8", "replace")), stamp
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410, 451):
                meta.write_text(json.dumps({"url": url, "status": exc.code, "retrieved_at": now()}))
                raise FetchError(f"HTTP {exc.code}") from exc
            if attempt == attempts - 1:
                raise FetchError(f"HTTP {exc.code}") from exc
            retry = exc.headers.get("Retry-After") if exc.headers else None
            time.sleep(min(120, int(retry) if retry and retry.isdigit() else 5 * 2 ** attempt))
        except Exception as exc:
            if attempt == attempts - 1:
                raise FetchError(str(exc)) from exc
            time.sleep(2 * 2 ** attempt)


def make_item(source, kind, key, text, url, applies_to, retrieved_at, role="document", fields=None, **extra):
    text = text.strip()
    item = {
        "id": hashlib.sha256(f"{source['id']}:{kind}:{key}".encode()).hexdigest()[:24],
        "source": source["id"], "kind": kind, "key": key, "role": role,
        "url": url, "retrieved_at": retrieved_at, "applies_to": sorted(set(applies_to)),
        "fields": fields or {}, "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(), "words": len(text.split()),
    }
    item.update(extra)
    return item


BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "pre", "blockquote", "table", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "hr", "dl", "dt", "dd", "details", "summary"]


def html_block_text(element):
    """Text of rendered post HTML with line breaks only between block elements.

    get_text("\\n") breaks a line at every inline element (links, code spans),
    which splits sentences; this keeps inline runs together and keeps the
    line breaks inside <pre> (indentation is not kept).
    """
    for node in element.find_all(string=True):
        if not node.find_parent("pre"):
            node.replace_with(re.sub(r"\s+", " ", node))
    for br in element.find_all("br"):
        br.replace_with("\n")
    for block in element.find_all(BLOCK_TAGS):
        block.insert_before("\n")
        block.insert_after("\n")
    lines = [line.strip() for line in element.get_text("").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def render_fields(fields):
    return "\n".join(f"{k}: {v}" for k, v in fields.items() if v)


def doc_text(doc):
    return (DATA / doc["text_path"]).read_text(encoding="utf-8", errors="replace")


def checkout_path(source, rel):
    return DATA / "checkouts" / source["id"] / rel


# --- GitHub threads -------------------------------------------------------

def github_thread(url):
    """Opening post of a GitHub issue or pull request page."""
    page, stamp = fetch(url)
    soup = BeautifulSoup(page, "html.parser")
    embedded = soup.find("script", attrs={"data-target": "react-app.embeddedData"})
    if embedded and embedded.string:
        try:
            payload = json.loads(embedded.string)
            issue = payload["payload"]["issueViewerRoute"]["data"]["repository"]["issue"]
            return {"title": issue.get("title", ""), "body": issue.get("body") or "",
                    "author": (issue.get("author") or {}).get("login"),
                    "created_at": issue.get("createdAt"), "url": issue.get("url") or url}, stamp
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    first = soup.select_one(".js-comment-container")
    body = first.select_one(".comment-body") if first else None
    if body is None:
        raise FetchError("No opening post found in page")
    title_el = soup.select_one(".js-issue-title, bdi.markdown-title")
    title = title_el.get_text(" ", strip=True) if title_el else (soup.title.get_text(" ", strip=True) if soup.title else "")
    title = re.sub(r"\s+·\s+(Pull Request|Issue) #\d+\s+·.*$", "", title)
    author = first.select_one("a.author")
    if author:
        title = re.sub(r"\s+by\s+" + re.escape(author.get_text(strip=True)) + r"$", "", title)
    when = first.select_one("relative-time[datetime]")
    return {"title": title, "body": html_block_text(body),
            "author": author.get_text(strip=True) if author else None,
            "created_at": when.get("datetime") if when else None, "url": url}, stamp


def thread_numbers(doc, text, rules):
    """Apply number-extraction rules in order; first match wins."""
    for rule in rules:
        where = rule["from"]
        if where == "identity":
            hay = doc["identity"]
        elif where == "header":
            hay = text[: rule.get("chars", 2500)]
        else:
            raise ValueError("Unknown number rule: " + where)
        m = re.search(rule["pattern"], hay)
        if m and int(m.group(1)):
            return m.group(1), where
    return None, None


def collect_github(source, docs, cfg):
    groups, numbered_from = defaultdict(list), {}
    for doc in docs:
        number, where = thread_numbers(doc, doc_text(doc), cfg["numbers"])
        if number:
            url = f"https://github.com/{cfg['repo']}/{cfg.get('path', 'issues')}/{int(number)}"
            groups[url].append(doc["id"])
            numbered_from[url] = where
    items, errors = [], []

    def one(url):
        info, stamp = github_thread(url)
        text = f"Title: {info['title']}\nOpened by {info['author'] or 'unknown'} on {info['created_at'] or 'unknown date'}\n\n{info['body']}"
        return make_item(source, cfg["kind"], url, text, url, groups[url], stamp,
                         label=cfg.get("label", cfg["kind"]), number_from=numbered_from[url],
                         fields={"title": info["title"], "author": info["author"], "created_at": info["created_at"]})

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(one, u): u for u in sorted(groups)}
        for future in concurrent.futures.as_completed(futures):
            try:
                items.append(future.result())
            except Exception as exc:
                errors.append({"collector": "github", "url": futures[future], "documents": groups[futures[future]], "error": str(exc)})
    return items, errors


# --- Document-local metadata ---------------------------------------------

def collect_header(source, docs, cfg):
    items = []
    keep = cfg.get("fields")
    for doc in docs:
        fields, _ = docmeta.parse_header(cfg["format"], doc_text(doc))
        if keep is not None:
            fields = {k: v for k, v in fields.items() if k in keep}
        fields = {k: re.sub(r"\s+", " ", v).strip() for k, v in fields.items() if v.strip()}
        if fields:
            items.append(make_item(source, "metadata", doc["id"], render_fields(fields), doc["url"], [doc["id"]],
                                   doc["retrieved_at"], fields=fields, label=cfg.get("label", "document header metadata")))
    return items, []


def collect_kep_yaml(source, docs, cfg):
    import yaml
    items, errors = [], []
    for doc in docs:
        path = checkout_path(source, doc["identity"]).parent / "kep.yaml"
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception as exc:  # malformed YAML or invalid dates in some kep.yaml files
            errors.append({"collector": "kep_yaml", "path": str(path), "error": str(exc)})
            continue
        fields = {}
        for k in cfg["fields"]:
            v = data.get(k)
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            if v not in (None, ""):
                fields[k] = str(v)
        rel = str(path.relative_to(DATA / "checkouts" / source["id"]))
        url = source["url"].removesuffix(".git") + "/blob/" + (doc["revision"] or "HEAD") + "/" + rel
        items.append(make_item(source, "metadata", rel + ":" + doc["id"], render_fields(fields), url, [doc["id"]],
                               doc["retrieved_at"], fields=fields, label="KEP metadata (kep.yaml)",
                               doc_role="proposal" if doc["identity"].endswith("/README.md") else "supporting document"))
    return items, errors


# --- Process documents ----------------------------------------------------

def github_repo(source):
    return re.sub(r"^https://github\.com/|\.git$", "", source["url"])


def file_history(repo, branch, path):
    """Commits that touched `path` on `branch`, newest first, as (committed_day, oid).

    Read from GitHub's commit-history page, which does not follow renames;
    sources.json lists a process file's former paths for that.
    """
    out, after = [], None
    while True:
        url = f"https://github.com/{repo}/commits/{branch}/{urllib.parse.quote(path)}"
        page, _ = fetch(url + (f"?after={urllib.parse.quote(after)}" if after else ""))
        route = None
        for script in BeautifulSoup(page, "html.parser").find_all("script", attrs={"data-target": "react-app.embeddedData"}):
            route = (json.loads(script.string or "{}").get("payload") or {}).get("commitsRefRoute") or route
        if route is None:
            raise FetchError("no commit history in " + url)
        out += [(docmeta.parse_date(c["committedDate"]), c["oid"]) for g in route["commitGroups"] for c in g["commits"]]
        pagination = route["filters"]["pagination"]
        if not pagination.get("hasNextPage"):
            return out
        after = pagination["endCursor"]


def collect_process(source, docs, cfg, dates=None):
    """Process documents and templates as they stood when each document was started.

    A version is the file at the last commit on or before the document's date
    (see document_dates); documents without a date, or older than every
    version, get no attachment. With `"versioned": false` the current file is
    attached to every document (and is excluded from briefs unless its
    `written` setting says it predates them).
    """
    by_identity = {d["identity"]: d for d in docs}
    items, errors = [], []
    if not cfg.get("versioned", True):
        for ref in cfg["files"]:
            doc = by_identity.get(ref)
            try:
                if doc:
                    text, url, stamp = doc_text(doc), doc["url"], doc["retrieved_at"]
                else:
                    data, stamp = fetch(ref, binary=True)
                    text, url = extract(data, ref), ref
            except Exception as exc:
                errors.append({"collector": "process", "ref": ref, "error": str(exc)})
                continue
            items.append(make_item(source, "process", ref, text, url, ["*"], stamp, role="process",
                                   document_id=doc["id"] if doc else None, label=f"{cfg.get('label', 'process document')}: {ref}"))
        return items, errors
    repo, branch = github_repo(source), cfg["branch"]
    dates = dates or {}
    for entry in cfg["files"]:
        ref = entry if isinstance(entry, str) else entry["path"]
        paths = [ref] + ([] if isinstance(entry, str) else entry.get("former_paths", []))
        try:
            # newest first; within a day, history order (newest first) breaks ties
            versions = [(day, oid, path) for day, _, oid, path in
                        sorted(((day, -pos, oid, path) for path in paths
                                for pos, (day, oid) in enumerate(file_history(repo, branch, path)) if day), reverse=True)]
        except Exception as exc:
            errors.append({"collector": "process", "ref": ref, "error": "history: " + str(exc)})
            continue
        self_id = by_identity[ref]["id"] if ref in by_identity else None
        users = defaultdict(list)
        for doc in docs:
            day = (dates.get(doc["id"]) or {}).get("date")
            if day and doc["id"] != self_id:
                users[day].append(doc["id"])
        texts, chosen = {}, defaultdict(list)
        for day in sorted(users, reverse=True):
            for vday, oid, path in versions:
                if vday > day:
                    continue
                if (oid, path) not in texts:
                    url = f"https://raw.githubusercontent.com/{repo}/{oid}/{urllib.parse.quote(path)}"
                    try:
                        texts[(oid, path)] = fetch(url)
                    except FetchError as exc:  # the commit that renamed or deleted the path
                        texts[(oid, path)] = None
                        if "404" not in str(exc):
                            errors.append({"collector": "process", "ref": ref, "url": url, "error": str(exc)})
                if texts[(oid, path)] is not None:
                    chosen[(vday, oid, path)].extend(users[day])
                    break
        for (vday, oid, path), applies in sorted(chosen.items()):
            text, stamp = texts[(oid, path)]
            items.append(make_item(source, "process", f"{ref}@{oid}", text, f"https://github.com/{repo}/blob/{oid}/{path}",
                                   applies, stamp, role="process", document_id=self_id,
                                   label=f"{cfg.get('label', 'process document')}: {ref} (version of {vday})",
                                   version={"path": path, "commit": oid, "committed": vday}, written_at=vday))
    return items, errors


def extract(data, url):
    if data.startswith(b"%PDF"):
        tmp = CTX / "raw" / "pdf" / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".pdf")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        return run(["pdftotext", "-layout", str(tmp), "-"], timeout=180)
    return page_text(data)[1]


# --- Index pages ----------------------------------------------------------

def index_entries(source, index_url, raw_index):
    """Map document URL -> index entry (link text, heading path, entry text)."""
    soup = BeautifulSoup(raw_index, "html.parser")
    root = soup.find("main") or soup.find("article") or soup.body or soup
    entries, headings = {}, {}
    for el in root.find_all(["h1", "h2", "h3", "h4", "a"]):
        if el.name != "a":
            level = int(el.name[1])
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = el.get_text(" ", strip=True)
            continue
        if not el.get("href"):
            continue
        url = urllib.parse.urljoin(index_url, el["href"]).split("#")[0]
        if url in entries:
            continue
        link_text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        block = el.find_parent(["li", "p", "dd", "td"])
        entry = re.sub(r"\s+", " ", block.get_text(" ", strip=True)) if block else link_text
        path = [headings[k] for k in sorted(headings)]
        if link_text.lower() in ("read more", "pdf", "download", "") and path:
            link_text, entry = path[-1], ""
            path = path[:-1]
        entries[url] = {"link_text": link_text, "entry_text": entry if entry != link_text else "", "headings": path}
    return entries


def collect_index(source, docs, cfg):
    index_url = cfg.get("url", source.get("index"))
    raw_path = DATA / "raw" / source["id"] / "index.html"
    if raw_path.exists() and index_url == source.get("index"):
        raw, stamp = raw_path.read_bytes(), datetime.fromtimestamp(raw_path.stat().st_mtime, timezone.utc).isoformat()
    else:
        raw, stamp = fetch(index_url, binary=True)
    entries = index_entries(source, index_url, raw)
    items = []
    for doc in docs:
        entry = entries.get(doc["url"]) or entries.get(doc.get("discovered_from_url", ""))
        if not entry:
            continue
        fields = {"Index section": " > ".join(h for h in entry["headings"] if h), "Title": entry["link_text"]}
        if entry["entry_text"]:
            fields["Index entry"] = entry["entry_text"]
        items.append(make_item(source, "index_entry", doc["id"], render_fields(fields), index_url, [doc["id"]], stamp,
                               fields=fields, label=cfg.get("label", "index entry"), group=" > ".join(entry["headings"])))
    if cfg.get("preamble"):
        text = index_preamble(raw, index_url, {d["url"] for d in docs})
        if text:
            items.append(make_item(source, "index_preamble", index_url, text, index_url,
                                   [i["applies_to"][0] for i in items], stamp, label="index page introduction"))
    return items, []


def index_preamble(raw_index, index_url, doc_urls):
    """Paragraphs of the index page that precede its first document link."""
    soup = BeautifulSoup(raw_index, "html.parser")
    root = soup.find("main") or soup.find("article") or soup.body or soup
    parts = []
    for el in root.find_all(["p", "a"]):
        if el.name == "a" and el.get("href") and urllib.parse.urljoin(index_url, el["href"]).split("#")[0] in doc_urls:
            break
        if el.name == "p":
            parts.append(re.sub(r"\s+", " ", el.get_text(" ", strip=True)))
    return "\n\n".join(p for p in parts if p)


def collect_markdown_index(source, docs, cfg):
    """Lines in sibling index files (e.g. a goal slate) that link to a document."""
    items = []
    by_dir = defaultdict(list)
    for doc in docs:
        by_dir[str(Path(doc["identity"]).parent)].append(doc)
    for folder, members in by_dir.items():
        for index_name in cfg["files"]:
            path = checkout_path(source, folder) / index_name
            if not path.exists():
                continue
            lines = path.read_text(errors="replace").splitlines()
            rel = str(Path(folder) / index_name)
            for doc in members:
                if doc["identity"] == rel:
                    continue
                name = Path(doc["identity"]).name
                hits = [l.strip() for l in lines if re.search(r"\]\(\.?/?" + re.escape(name) + r"\)", l)]
                if hits:
                    url = source["url"].removesuffix(".git") + "/blob/" + (doc["revision"] or "HEAD") + "/" + rel
                    items.append(make_item(source, "index_entry", rel + ":" + doc["id"], "\n".join(hits[:3]), url, [doc["id"]],
                                           doc["retrieved_at"], label=f"entry in {rel}", index_document=rel))
    return items, []


# --- Python discussion threads -------------------------------------------

# topic URLs with or without the slug (/t/some-title/123, /t/123); a slug always has a non-digit
DISCUSS = re.compile(r"https://discuss\.python\.org/t/(?:[\w-]*[^\W\d][\w-]*/)?(\d+)")


def collect_discourse(source, docs, cfg):
    """Opening posts of every discuss.python.org thread a PEP header names.

    Discussions-To usually announces the drafted PEP, while Post-History can
    also list pre-PEP threads that predate it; cases.py keeps only threads
    opened on or before the PEP's Created date.
    """
    groups = defaultdict(list)
    for doc in docs:
        fields, _ = docmeta.parse_header("rfc822", doc_text(doc))
        topics = DISCUSS.findall(fields.get("Discussions-To", "") + "\n" + fields.get("Post-History", ""))
        for topic in dict.fromkeys(topics):
            groups[topic].append(doc["id"])
    items, errors = [], []

    def one(topic):
        url = f"https://discuss.python.org/t/{topic}.json"
        data, stamp = fetch(url)
        payload = json.loads(data)
        post = payload["post_stream"]["posts"][0]
        body = html_block_text(BeautifulSoup(post.get("cooked", ""), "html.parser"))
        text = f"Title: {payload.get('title', '')}\nOpened by {post.get('username')} on {post.get('created_at')}\n\n{body}"
        return make_item(source, "discussion_thread", topic, text, f"https://discuss.python.org/t/{topic}", groups[topic], stamp,
                         label="discussion thread opening post", fields={"title": payload.get("title"), "created_at": post.get("created_at")})

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(one, t): t for t in sorted(groups)}
        for future in concurrent.futures.as_completed(futures):
            try:
                items.append(future.result())
            except Exception as exc:
                errors.append({"collector": "discourse", "topic": futures[future], "error": str(exc)})
    return items, errors


# --- Oxide RFD index ------------------------------------------------------

def collect_oxide(source, docs, cfg):
    data, stamp = fetch(cfg["api"])
    entries = {int(r["rfd_number"]): r for r in json.loads(data)}
    items = []
    for doc in docs:
        m = re.search(r"/rfd/(\d+)$", doc["identity"])
        entry = m and entries.get(int(m.group(1)))
        if not entry:
            continue
        fields = {"RFD": str(entry["rfd_number"]), "Title": entry.get("title"), "Authors": entry.get("authors"),
                  "Labels": entry.get("labels")}
        fields = {k: v for k, v in fields.items() if v}
        items.append(make_item(source, "index_entry", str(entry["rfd_number"]), render_fields(fields),
                               "https://rfd.shared.oxide.computer/rfd/" + m.group(1).zfill(4), [doc["id"]], stamp,
                               fields=fields, label="RFD index entry"))
    return items, []


# --- IETF -----------------------------------------------------------------

def rfc_index():
    data, stamp = fetch("https://www.rfc-editor.org/rfc-index.xml", binary=True)
    ns = {"r": "https://www.rfc-editor.org/rfc-index"}
    root = ET.fromstring(data)
    out = {}
    for e in root.findall("r:rfc-entry", ns):
        get = lambda tag: (e.findtext("r:" + tag, default="", namespaces=ns) or "").strip()
        number = int(get("doc-id")[3:])
        month, year = e.findtext("r:date/r:month", default="", namespaces=ns), e.findtext("r:date/r:year", default="", namespaces=ns)
        rels = lambda tag: [d.text for d in e.findall(f"r:{tag}/r:doc-id", ns)]
        out[number] = {
            "number": number, "title": get("title"),
            "authors": [a.findtext("r:name", default="", namespaces=ns) for a in e.findall("r:author", ns)],
            "month": month, "year": year, "draft": get("draft"), "stream": get("stream"), "area": get("area"),
            "wg": get("wg_acronym"), "category": get("publication-status"),
            "obsoletes": rels("obsoletes"), "updates": rels("updates"),
        }
    return out, stamp


def datatracker_all(path):
    out, url = [], "https://datatracker.ietf.org" + path
    while url:
        data, _ = fetch(url)
        page = json.loads(data)
        out.extend(page["objects"])
        url = "https://datatracker.ietf.org" + page["meta"]["next"] if page["meta"].get("next") else None
    return out


def ietf_numbers(source, doc):
    m = re.fullmatch(r"rfc(\d+)\.(?:txt|md)", Path(doc["identity"]).name)
    return int(m.group(1)) if m else None


def first_draft_dates():
    """Draft name -> day its -00 revision was submitted, from the datatracker's revision events.

    Events start with the datatracker (around 2001); older drafts have none.
    """
    out = {}
    for event in datatracker_all("/api/v1/doc/newrevisiondocevent/?format=json&limit=1000&rev=00&doc__type=draft"):
        name = event["doc"].rstrip("/").rsplit("/", 1)[-1]
        day = docmeta.parse_date(event["time"])
        if day and (name not in out or day < out[name]):
            out[name] = day
    return out


def charter_written_by(events):
    """Charter revision -> (time its text is known to exist by, basis), from its new_revision events.

    A revision approved in the datatracker follows proposals numbered after
    the previous revision (`06-00`, then `07`; `00-00`, then `01` for a new
    group), and its event is the approval. Other revisions carry the day they
    were entered, mostly from the legacy charter archive imported on
    2009-08-29, except the charter's first event, which is usually stamped
    with the group's start date whatever its text (pppext's 01, stamped 1989, cites
    RFC 1661 from 1994; dhc's, stamped 1991, gives RFC 2131's status; dmm's
    cites a 2011 RFC). That revision is known to exist only by the charter's
    next event (a later revision or a proposal); without one it is left
    undated. Revision 00 is a new group's placeholder with no charter text.
    """
    times, proposed = {}, set()
    for e in events:
        if re.fullmatch(r"\d\d", e["rev"]):
            times[e["rev"]] = min(times.get(e["rev"], e["time"]), e["time"])
        elif re.fullmatch(r"\d\d-\d\d", e["rev"]):
            proposed.add(e["rev"][:2])
    start = min((e["time"] for e in events), default=None)
    out = {}
    for rev, t in times.items():
        if rev == "00":
            continue
        if f"{int(rev) - 1:02d}" in proposed:
            out[rev] = (t, "approved")
        elif t != start:
            out[rev] = (t, "entered")
        else:
            later = [e["time"] for e in events if e["time"] > t]
            if later:
                out[rev] = (min(later), "entered")
    return out


def charter_in_force(known, first):
    """The latest charter revision whose text is known to exist by day `first`, or None.

    Picked by revision number, not by date: a concluded group's 01 can be
    stamped with a later date (btns' 01 carries 2010-03-16, after 02 and 03
    were imported in 2009), which would otherwise outrank the revisions that
    replaced it.
    """
    usable = [rev for rev, (t, _) in known.items() if docmeta.parse_date(t) <= first]
    return max(usable, default=None)


def collect_ietf(source, docs, cfg):
    index, stamp = rfc_index()
    items, errors = [], []
    try:
        first_drafts = first_draft_dates()
    except Exception as exc:
        first_drafts = {}
        errors.append({"collector": "ietf_first_drafts", "error": str(exc)})
    by_wg = defaultdict(list)
    drafts = {}
    for doc in docs:
        number = ietf_numbers(source, doc)
        entry = index.get(number) if number else None
        if not entry:
            continue
        fields = {"RFC number": str(number), "Title": entry["title"], "Authors": ", ".join(entry["authors"]),
                  "Published": f"{entry['month']} {entry['year']}", "Stream": entry["stream"],
                  "Area": entry["area"], "Working group": entry["wg"] if entry["wg"] != "NON WORKING GROUP" else "",
                  "Category": entry["category"], "Source draft": re.sub(r"-\d\d$", "", entry["draft"]),
                  "Obsoletes": ", ".join(entry["obsoletes"]), "Updates": ", ".join(entry["updates"])}
        draft_name = re.sub(r"-\d\d$", "", entry["draft"]) if entry["draft"] else ""
        first = first_drafts.get(draft_name)
        fields["First draft submitted"] = first or ""
        fields = {k: v for k, v in fields.items() if v}
        items.append(make_item(source, "index_entry", f"rfc{number}:{doc['id']}", render_fields(fields),
                               f"https://www.rfc-editor.org/info/rfc{number}", [doc["id"]], stamp, fields=fields,
                               label="RFC Editor index entry (abstract excluded)"))
        if entry["wg"] and entry["wg"] != "NON WORKING GROUP" and first:
            by_wg[entry["wg"]].append((doc["id"], first))
        if draft_name:
            drafts.setdefault(draft_name, []).append(doc["id"])
    if not cfg.get("charters", True):
        return items, errors
    try:
        groups = {g["acronym"]: g for g in datatracker_all("/api/v1/group/group/?format=json&limit=1000&type__in=wg&type__in=rg&type__in=ag")}
    except Exception as exc:
        return items, errors + [{"collector": "ietf", "error": "group list: " + str(exc)}]

    def charter(wg):
        group = groups.get(wg)
        if not group or not group.get("charter"):
            raise FetchError("no charter document recorded")
        name = group["charter"].rstrip("/").rsplit("/", 1)[-1]
        known = charter_written_by(datatracker_all(
            f"/api/v1/doc/docevent/?format=json&limit=200&type=new_revision&doc__name={name}"))
        out = []
        for doc_id, first in by_wg[wg]:
            # the charter in force when the source draft was first submitted, not a later revision
            rev = charter_in_force(known, first)
            if rev:
                out.append((rev, doc_id))
        made, errs = [], []
        for rev in sorted({r for r, _ in out}):
            url = f"https://www.ietf.org/charter/{name}-{rev}.txt"
            applies = [d for r, d in out if r == rev]
            try:
                text, got = fetch(url)
            except FetchError as exc:
                errs.append({"collector": "ietf_charter", "group": wg, "url": url, "documents": len(applies), "error": str(exc)})
                continue
            t, basis = known[rev]
            when = f"approved {t[:10]}" if basis == "approved" else f"on record by {t[:10]}"
            made.append(make_item(source, "charter", f"{name}-{rev}", text, url, applies, got,
                                  label=f"working group charter ({wg}, revision {rev}, {when})",
                                  fields={"group": wg, "revision": rev, "written_by": t, "dated_by": basis},
                                  written_at=docmeta.parse_date(t)))
        return made, errs

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(charter, wg): wg for wg in sorted(by_wg)}
        for future in concurrent.futures.as_completed(futures):
            try:
                made, errs = future.result()
                items.extend(made)
                errors.extend(errs)
            except Exception as exc:
                errors.append({"collector": "ietf_charter", "group": futures[future], "documents": len(by_wg[futures[future]]), "error": str(exc)})
    try:
        milestones = datatracker_all("/api/v1/group/groupmilestone/?format=json&limit=1000")
        milestones += datatracker_all("/api/v1/group/groupmilestonehistory/?format=json&limit=1000")
    except Exception as exc:
        return items, errors + [{"collector": "ietf_milestones", "error": str(exc)}]
    group_names = {g["resource_uri"]: g["acronym"] for g in groups.values()}
    per_draft = defaultdict(dict)
    for m in milestones:
        for d in m.get("docs", []):
            name = d.rstrip("/").rsplit("/", 1)[-1]
            if name in drafts:
                per_draft[name].setdefault(m["desc"].strip(), (m.get("due"), group_names.get(m["group"], "")))
    for name, descs in per_draft.items():
        text = "\n".join(f"- {desc}" + (f" (due {due})" if due else "") for desc, (due, _) in sorted(descs.items()))
        wg = next(iter(descs.values()))[1]
        items.append(make_item(source, "milestone", name, text, f"https://datatracker.ietf.org/group/{wg}/about/",
                               drafts[name], now(), label=f"working group milestones naming {name}",
                               fields={"draft": name, "group": wg}))
    return items, errors


# --- Study calls ----------------------------------------------------------

def collect_study_call(source, docs, cfg):
    groups = {}
    if cfg.get("match_group"):
        raw_path = DATA / "raw" / source["id"] / "index.html"
        entries = index_entries(source, source["index"], raw_path.read_bytes())
        groups = {d["id"]: " > ".join(entries.get(d["url"], {}).get("headings", [])) for d in docs}
    applies = [d["id"] for d in docs if not cfg.get("match_group") or cfg["match_group"] in groups.get(d["id"], "")]
    items, errors = [], []
    for url in cfg["urls"]:
        try:
            data, stamp = fetch(url, binary=True)
            text = extract(data, url)
            if cfg.get("start_marker") and cfg["start_marker"] in text:
                text = text[text.index(cfg["start_marker"]):]
            if cfg.get("end_marker") and cfg["end_marker"] in text:
                text = text[: text.index(cfg["end_marker"])]
            if cfg.get("strip_pattern"):
                text = re.sub(cfg["strip_pattern"], "\n", text, flags=re.S)
        except Exception as exc:
            errors.append({"collector": "study_call", "url": url, "error": str(exc)})
            continue
        items.append(make_item(source, "study_call", url, text, url, applies, stamp, label=cfg["label"],
                               fields={"group": cfg.get("match_group", "")}))
    return items, errors


COLLECTORS = {
    "github": collect_github, "header": collect_header, "kep_yaml": collect_kep_yaml, "process": collect_process,
    "index": collect_index, "markdown_index": collect_markdown_index, "discourse": collect_discourse,
    "oxide": collect_oxide, "ietf": collect_ietf, "study_call": collect_study_call,
}


def documents_by_source():
    out = defaultdict(list)
    for line in (DATA / "corpus.jsonl").read_text().splitlines():
        row = json.loads(line)
        out[row["source"]].append(row)
    return out


TIMINGS = {"before", "with_document", "identity", "dated", "after"}


def stamp_timing(item, cfg):
    """Record when an item was written relative to its documents (see sources.json `written`).

    before: predates the document by construction (study calls, charters and
    template versions chosen by date); with_document: the document's own
    metadata; identity: a record written after the document, reduced to the
    fields that identify it; dated: compared by date in cases.py; after:
    written after the document and never used in a brief.
    """
    written = cfg["written"]
    if isinstance(written, dict):
        written = written[item["kind"]]
    if written not in TIMINGS:
        raise ValueError(f"unknown written setting {written!r}")
    item["written"] = written
    item.setdefault("written_at", docmeta.parse_date(item["fields"].get("created_at")))
    if written == "identity":
        keep = cfg["identity_fields"]
        item["fields_withheld"] = sorted(k for k in item["fields"] if k not in keep)
        item["text"] = render_fields({k: item["fields"][k] for k in keep if item["fields"].get(k)})
        item["sha256"] = hashlib.sha256(item["text"].encode()).hexdigest()
        item["words"] = len(item["text"].split())
    note = cfg.get("written_note")
    item["written_note"] = note.get(item["kind"]) if isinstance(note, dict) else note
    return item


def document_dates(source, docs, items):
    """Per document, the latest date known not to follow the start of its writing, with its basis."""
    rule = source["context"].get("document_date")
    out = {}
    if not rule:
        return out
    by_doc = defaultdict(list)
    for item in items:
        for doc_id in item["applies_to"]:
            by_doc[doc_id].append(item)
    for doc in docs:
        day = None
        for item in by_doc.get(doc["id"], []):
            if rule["from"] == "metadata" and item["kind"] == "metadata":
                day = docmeta.parse_date(item["fields"].get(rule["field"]))
            elif rule["from"] == "item" and item["kind"] == rule["kind"] and item.get("number_from") == rule.get("number_from"):
                day = item.get("written_at")
            elif rule["from"] == "ietf_first_draft" and item["kind"] == "index_entry":
                day = docmeta.parse_date(item["fields"].get("First draft submitted"))
            if day:
                break
        if day:
            out[doc["id"]] = {"date": day, "basis": rule["basis"]}
    return out


def collect_context(source, docs):
    items, errors = [], []
    collectors = source["context"]["collectors"]
    dates = None
    # process collectors run last: template versions are chosen by document date
    for cfg in sorted(collectors, key=lambda c: c["type"] == "process"):
        if cfg["type"] == "process" and dates is None:
            dates = document_dates(source, docs, items)
        selected = [d for d in docs if re.search(cfg.get("documents", ""), d["identity"])]
        try:
            if cfg["type"] == "process":
                got, errs = collect_process(source, selected, cfg, dates)
            else:
                got, errs = COLLECTORS[cfg["type"]](source, selected, cfg)
            got = [stamp_timing(i, cfg) for i in got]
        except Exception as exc:
            got, errs = [], [{"collector": cfg["type"], "error": f"{type(exc).__name__}: {exc}"}]
        items.extend(got)
        errors.extend(errs)
    if dates is None:
        dates = document_dates(source, docs, items)
    CTX.mkdir(parents=True, exist_ok=True)
    unique = {i["id"]: i for i in items}
    (CTX / (source["id"] + ".jsonl")).write_text("".join(json.dumps(i) + "\n" for i in sorted(unique.values(), key=lambda i: i["id"])))
    (CTX / (source["id"] + ".dates.json")).write_text(json.dumps(dates, indent=1, sort_keys=True) + "\n")
    status = {"source": source["id"], "items": len(unique), "documents_with_items": len({d for i in unique.values() if i["role"] != "process" for d in i["applies_to"]}),
              "documents_dated": len(dates),
              "by_kind": dict(sorted({k: sum(1 for i in unique.values() if i["kind"] == k) for k in {i["kind"] for i in unique.values()}}.items())),
              "by_written": dict(sorted({w: sum(1 for i in unique.values() if i["written"] == w) for w in {i["written"] for i in unique.values()}}.items())),
              "errors": errors, "finished_at": now()}
    (CTX / (source["id"] + ".status.json")).write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps({k: (len(v) if k == "errors" else v) for k, v in status.items()}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", nargs="*")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    sources = [s for s in json.loads((HERE / "sources.json").read_text())["sources"] if s.get("context", {}).get("collectors")]
    if args.sources:
        unknown = set(args.sources) - {s["id"] for s in sources}
        if unknown:
            parser.error("Sources without context collectors: " + ", ".join(sorted(unknown)))
        sources = [s for s in sources if s["id"] in args.sources]
    docs = documents_by_source()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda s: collect_context(s, docs[s["id"]]), sources))


if __name__ == "__main__":
    main()
