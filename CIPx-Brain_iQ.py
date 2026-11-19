# NEW IN 1.0: three standard-library imports (nothing to install).
#   os   - file paths, folders and file sizes for backups
#   sys  - stop cleanly if the database is damaged
#   json - the portable export format
import os
import sys
import json
# NEW IN 1.2: io and contextlib let :learn and :update run the
# existing step commands quietly and print one short summary.
import io
import contextlib
import sqlite3
import hashlib
import re
import math
import shlex
from datetime import datetime
from collections import defaultdict

# ==========================================
# CIPx | BRAIN iQ
# Version 1.2
# Local Knowledge Acquisition, Digests, Recovery & Review
#
# Changes from 1.1 (Milestone 8, step 2 - automatic checks):
#   1. :learn "topic" runs extract, associate, digest and the
#      automatic checks in one command.
#   2. :update extracts, classifies and associates everything, then
#      re-checks every provisional or supported digest.
#   3. A digest that passes every check becomes "supported"
#      (system-checked). BRAIN never sets "established" and never
#      changes a status you set: established and rejected items are
#      left alone. A supported digest that later fails goes back to
#      provisional.
#   4. The checks: breadth (3+ records from 2+ content items), no
#      rejection nearby, and faithfulness (every quoted sentence is
#      still found word for word in its sources).
#   Everything else behaves exactly as in 1.1.
#
# Changes from 1.0 (Milestone 8, step 1 - reviewing knowledge):
#   1. Knowledge Body items can be confirmed or rejected:
#        :confirm knowledge 3      :reject knowledge 3
#      (:confirm 1 and :reject 1 still act on LINKS, as before.)
#   2. Rejected items stay stored, with the date of the review, but
#      are hidden from :retrieve. :knowledge still lists them.
#   3. Rebuilding a digest identical to a rejected one leaves it
#      rejected, so it is not reviewed twice.
#   Acquisition, extraction, association, recovery and the rest of
#   retrieval behave exactly as in 1.0.
#
# Changes from 0.9 to 1.0 (Milestone 9 - recovery; complete, with a
# manual restore):
#   1. The database path always resolves beside this script.
#   2. A SQLite integrity check runs at every startup.
#   3. :backup makes a verified, recoverable copy of the database.
#   4. :export writes a portable, checksummed JSON export.
#   Acquisition, extraction, association and retrieval behave
#   exactly as in 0.9; nothing in those sections was changed.
#
# Changes from 0.8 (made in 0.9):
#   1. Only lines starting with ":" are parsed as commands, so normal
#      text (apostrophes, quotes) is always saved. Added :paste.
#   2. Content is split into sections (many Context records per
#      Content item). Existing databases are migrated automatically.
#   3. "Synthesis" is now an honest, capped, source-grouped evidence
#      digest, and link expansion actually works.
# ==========================================

# ------------------------------------------
# NEW IN 1.0 (step 1): DATABASE LOCATION
# ------------------------------------------
# Before: "brain_iq.db" was created in whichever folder the program was
# launched from, so starting it from a different folder silently began
# a new, empty brain. Now everything BRAIN writes (database, backups,
# exports) lives beside this script, so the whole brain travels
# together on one drive.

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "brain_iq.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")

# Messages gathered while starting up; shown under the banner.
startup_notes = []


# NEW IN 1.0: Safety net for the path change above. If a database sits
# in the folder you launched from but none exists beside the script,
# stop instead of quietly creating an empty one. Nothing is moved or
# changed; you are told exactly what to copy and where.
def stop_if_database_left_behind():

    launch_copy = os.path.abspath("brain_iq.db")

    if (
        os.path.normcase(launch_copy) != os.path.normcase(DATABASE)
        and os.path.exists(launch_copy)
        and not os.path.exists(DATABASE)
    ):
        print("\nA database was found in the folder you launched from:")
        print("  " + launch_copy)
        print("BRAIN now keeps its database beside the script:")
        print("  " + DATABASE)
        print("\nNothing has been changed. To keep your existing")
        print("knowledge, close this program and copy that file to the")
        print("location above (or move brain_iq.py next to it).")
        sys.exit(1)


stop_if_database_left_behind()

db = sqlite3.connect(DATABASE)
db.execute("PRAGMA foreign_keys = ON")


# ------------------------------------------
# NEW IN 1.0 (step 2): STARTUP INTEGRITY CHECK
# ------------------------------------------
# Runs SQLite's own integrity check before BRAIN touches anything.
# If damage is found, BRAIN stops WITHOUT writing to the file, so the
# damaged database is left exactly as it was for any later recovery
# attempt. A separate warning (not a stop) is shown if records point
# at records that no longer exist.
def run_startup_integrity_check():

    try:
        rows = db.execute("PRAGMA integrity_check").fetchall()

    except sqlite3.DatabaseError as error:
        rows = [(str(error),)]

    problems = [row[0] for row in rows if row[0] != "ok"]

    if problems:
        print("\n========== DATABASE PROBLEM ==========")
        print("SQLite reports damage in:")
        print("  " + DATABASE)

        for problem in problems[:10]:
            print("  -", problem)

        if len(problems) > 10:
            print(f"  ... and {len(problems) - 10} more.")

        print("\nBRAIN has stopped without changing anything.")
        print("Keep this file as it is. To recover, restore a backup")
        print("from:")
        print("  " + BACKUP_DIR)
        print("(the restore note is printed by :backup)")
        print("======================================")

        db.close()
        sys.exit(1)

    startup_notes.append("Database integrity check: OK")

    try:
        orphans = db.execute("PRAGMA foreign_key_check").fetchall()

    except sqlite3.DatabaseError:
        orphans = []

    if orphans:
        startup_notes.append(
            f"WARNING: {len(orphans)} records point to missing "
            "records. BRAIN will still run; run :backup and "
            ":export now."
        )


run_startup_integrity_check()

cursor = db.cursor()


# ==========================================
# 1. FOUNDATION
# ==========================================

def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def get_columns(table):
    cursor.execute(f"PRAGMA table_info({quote(table)})")
    return {
        row[1].lower(): {
            "name": row[1],
            "not_null": bool(row[3]),
            "default": row[4],
            "primary_key": bool(row[5])
        }
        for row in cursor.fetchall()
    }


# ==========================================
# 2. CONTENT BODY
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS content_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    content TEXT NOT NULL,
    status TEXT DEFAULT 'acquired'
)
""")

db.commit()

content_columns = get_columns("content_items")

if "id" not in content_columns:
    raise RuntimeError("Content Body has no ID column.")

if "content" not in content_columns:
    raise RuntimeError("Content Body has no Content column.")

id_col = content_columns["id"]["name"]
content_col = content_columns["content"]["name"]


# ==========================================
# 3. CONTEXT BODY (now one record per SECTION)
# ==========================================

CONTEXT_TABLE_SQL = """
CREATE TABLE {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    section_index INTEGER NOT NULL DEFAULT 0,
    type TEXT DEFAULT 'source_section',
    title TEXT,
    content TEXT NOT NULL,
    status TEXT DEFAULT 'unprocessed',
    created_at TEXT,
    UNIQUE(source_id, section_index)
)
"""


def migrate_context_items():
    """
    Older databases had UNIQUE(source_id), which allowed only one Context
    record per Content item. SQLite cannot drop a constraint in place, so
    rebuild the table. Existing records keep their IDs (links and
    knowledge provenance stay valid) and become section 0.
    """
    print("Upgrading Context Body to support sections...")
    db.commit()

    script = (
        "PRAGMA foreign_keys = OFF;\n"
        "BEGIN;\n"
        + CONTEXT_TABLE_SQL.format(name="context_items_new") + ";\n"
        "INSERT INTO context_items_new "
        "(id, source_id, section_index, type, title, content, "
        "status, created_at) "
        "SELECT id, source_id, 0, type, title, content, "
        "status, created_at FROM context_items;\n"
        "DROP TABLE context_items;\n"
        "ALTER TABLE context_items_new RENAME TO context_items;\n"
        "COMMIT;\n"
        "PRAGMA foreign_keys = ON;\n"
    )

    try:
        db.executescript(script)

    except Exception:
        if db.in_transaction:
            db.rollback()
        db.execute("PRAGMA foreign_keys = ON")
        raise

    print("Upgrade complete. Run :extract to split existing records.")


cursor.execute(
    CONTEXT_TABLE_SQL.format(name="IF NOT EXISTS context_items")
)
db.commit()

if "section_index" not in get_columns("context_items"):
    migrate_context_items()

context_columns = get_columns("context_items")

required_context_columns = [
    "id", "source_id", "section_index", "type",
    "title", "content", "status"
]

for column in required_context_columns:
    if column not in context_columns:
        raise RuntimeError(
            "Context Body is missing column: " + column
        )


# ==========================================
# 4. CONTEXT LINKS
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS context_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_context_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    target_context_id INTEGER NOT NULL,
    status TEXT DEFAULT 'provisional',
    created_at TEXT,
    UNIQUE (
        source_context_id,
        relationship_type,
        target_context_id
    ),
    CHECK (source_context_id != target_context_id),
    FOREIGN KEY (source_context_id)
        REFERENCES context_items(id),
    FOREIGN KEY (target_context_id)
        REFERENCES context_items(id)
)
""")

link_columns = get_columns("context_links")

for column, data_type in {
    "evidence": "TEXT",
    "confidence": "REAL",
    "method": "TEXT"
}.items():

    if column not in link_columns:
        cursor.execute(
            f"ALTER TABLE context_links "
            f"ADD COLUMN {quote(column)} {data_type}"
        )

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_context_link_source
ON context_links(source_context_id)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_context_link_target
ON context_links(target_context_id)
""")

db.commit()


# ==========================================
# 5. KNOWLEDGE BODY
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS knowledge_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT DEFAULT 'provisional',
    created_at TEXT,
    method TEXT,
    source_count INTEGER DEFAULT 0,
    content_hash TEXT UNIQUE
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id INTEGER NOT NULL,
    context_id INTEGER NOT NULL,
    source_rank INTEGER,
    relevance REAL,
    created_at TEXT,
    UNIQUE(knowledge_id, context_id),
    FOREIGN KEY (knowledge_id)
        REFERENCES knowledge_items(id)
        ON DELETE CASCADE,
    FOREIGN KEY (context_id)
        REFERENCES context_items(id)
)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_knowledge_source_knowledge
ON knowledge_sources(knowledge_id)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_knowledge_source_context
ON knowledge_sources(context_id)
""")

# NEW IN 1.1: one extra column recording WHEN a Knowledge Body item was
# confirmed or rejected, so a rejection stays on the record. It is
# added to existing databases automatically (nothing is rewritten and
# every existing row keeps its data; reviewed_at is simply empty until
# an item is reviewed).
if "reviewed_at" not in get_columns("knowledge_items"):
    cursor.execute(
        "ALTER TABLE knowledge_items ADD COLUMN reviewed_at TEXT"
    )

# NEW IN 1.2: two more columns, added the same way. checked_at records
# when BRAIN last ran its automatic checks on an item, and check_notes
# keeps what each rule found, so a result can always be read later.
for new_column in ("checked_at", "check_notes"):
    if new_column not in get_columns("knowledge_items"):
        cursor.execute(
            f"ALTER TABLE knowledge_items ADD COLUMN {new_column} TEXT"
        )

db.commit()


# ==========================================
# 6. ACQUIRE CONTENT
# ==========================================

def acquire_content(message):

    if not message or not message.strip():
        print("Nothing to save.")
        return

    now = timestamp()
    first_line = message.strip().splitlines()[0][:150]

    content_hash = hashlib.sha256(
        message.encode("utf-8")
    ).hexdigest()

    session = now.replace(
        "-", ""
    ).replace(
        ":", ""
    ).replace(
        " ", ""
    )

    known_values = {
        "content": message,
        "date": now,
        "created_at": now,
        "timestamp": now,
        "session_id": session,
        "kind": "text",
        "title": first_line,
        "source": "user_input",
        "content_hash": content_hash,
        "status": "acquired"
    }

    fields = []
    values = []

    for lower_name, details in content_columns.items():

        column_name = details["name"]

        if details["primary_key"]:
            continue

        if lower_name in known_values:
            fields.append(quote(column_name))
            values.append(known_values[lower_name])

        elif (
            details["not_null"]
            and details["default"] is None
        ):
            fields.append(quote(column_name))
            values.append("")

    placeholders = ", ".join(["?"] * len(fields))

    sql = (
        "INSERT INTO content_items ("
        + ", ".join(fields)
        + ") VALUES ("
        + placeholders
        + ")"
    )

    try:
        cursor.execute(sql, values)
        db.commit()
        print("Content acquired.")

    except sqlite3.IntegrityError as error:
        print("Content was not saved:", error)


def paste_content():
    """Collect several lines as ONE Content item."""

    print("Paste your text. Finish with a line containing only :end")
    print("(or :cancel to abort).")

    lines = []

    while True:

        try:
            line = input()

        except EOFError:
            break

        marker = line.strip().lower()

        if marker == ":end":
            break

        if marker == ":cancel":
            print("Cancelled.")
            return

        lines.append(line)

    text = "\n".join(lines).strip()

    if not text:
        print("Nothing to save.")
        return

    acquire_content(text)


# ==========================================
# 7. RETRIEVE CONTENT BODY
# ==========================================

def retrieve_content():

    cursor.execute(
        f"SELECT * FROM content_items "
        f"ORDER BY {quote(id_col)} ASC"
    )

    records = cursor.fetchall()

    if not records:
        print("\nContent Body is empty.")
        return

    print("\n========== CONTENT BODY ==========")

    for record in records:
        print("\n----------------------------------")

        for index, value in enumerate(record):
            print(f"{index}: {value}")

    print("\n==================================")


# ==========================================
# 8. EXTRACT INTO CONTEXT BODY (sections)
# ==========================================

MIN_SECTION_CHARS = 200
MAX_SECTION_CHARS = 1500

HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def split_long_text(text, limit):
    """Split oversized text into chunks of at most `limit` characters,
    preferring sentence boundaries."""

    if len(text) <= limit:
        return [text]

    pieces = [
        piece.strip()
        for piece in re.split(r"(?<=[.!?])\s+|\n+", text)
        if piece.strip()
    ]

    chunks = []
    current = ""

    for piece in pieces:

        if current and len(current) + 1 + len(piece) > limit:
            chunks.append(current)
            current = piece

        else:
            current = (current + " " + piece) if current else piece

        while len(current) > limit:
            cut = current.rfind(" ", 0, limit)

            if cut < limit // 2:
                cut = limit

            chunks.append(current[:cut].strip())
            current = current[cut:].strip()

    if current:
        chunks.append(current)

    return chunks


def first_line_title(text):

    for line in text.splitlines():
        title = line.strip().lstrip("#").strip()

        if title:
            return title[:80]

    return "Untitled source section"


def split_into_sections(content):
    """
    Return a list of (title, text) sections.

    - If the text has Markdown headings, each heading starts a section.
    - Otherwise paragraphs (blank-line separated) are grouped until each
      section is at least MIN_SECTION_CHARS.
    - Anything over MAX_SECTION_CHARS is split at sentence boundaries.
    """

    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()

    if not text:
        return []

    lines = text.split("\n")
    blocks = []

    if any(HEADING_PATTERN.match(line) for line in lines):

        groups = [{"heading": None, "lines": []}]

        for line in lines:

            if HEADING_PATTERN.match(line):
                groups.append({
                    "heading": line.strip().lstrip("#").strip(),
                    "lines": [line]
                })

            else:
                groups[-1]["lines"].append(line)

        carry = ""

        for group in groups:

            body = "\n".join(group["lines"]).strip()

            if not body:
                continue

            # A heading with no body is carried into the next section.
            if group["heading"] and len(group["lines"]) == 1:
                carry = (carry + "\n" + body).strip()
                continue

            if carry:
                body = carry + "\n" + body
                carry = ""

            blocks.append((group["heading"], body))

        if carry:
            blocks.append((None, carry))

    else:

        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", text)
            if p.strip()
        ]

        merged = []
        buffer = ""

        for paragraph in paragraphs:

            buffer = (
                buffer + "\n\n" + paragraph
                if buffer else paragraph
            )

            if len(buffer) >= MIN_SECTION_CHARS:
                merged.append(buffer)
                buffer = ""

        if buffer:
            if merged:
                merged[-1] += "\n\n" + buffer
            else:
                merged.append(buffer)

        blocks = [(None, block) for block in merged]

    sections = []

    for heading, body in blocks:

        chunks = split_long_text(body, MAX_SECTION_CHARS)

        for number, chunk in enumerate(chunks, 1):

            title = (heading or first_line_title(chunk))[:130]

            if len(chunks) > 1:
                title += f" (part {number})"

            sections.append((title, chunk))

    return sections


def extract_context():

    cursor.execute(
        f"SELECT {quote(id_col)}, {quote(content_col)} "
        f"FROM content_items ORDER BY {quote(id_col)} ASC"
    )

    records = cursor.fetchall()
    extracted = 0
    upgraded = 0

    for source_id, content in records:

        sections = split_into_sections(content)

        if not sections:
            continue

        # Records created before sections existed hold the whole item
        # as section 0. Shrink that record to the first section (its ID,
        # and so its links, are kept) and add the rest below.
        cursor.execute("""
            SELECT id, content
            FROM context_items
            WHERE source_id = ? AND section_index = 0
        """, (source_id,))

        existing = cursor.fetchone()

        if (
            existing
            and len(sections) > 1
            and existing[1] == content
        ):
            first_title, first_text = sections[0]

            cursor.execute("""
                UPDATE context_items
                SET title = ?, content = ?,
                    type = 'source_section', status = 'unprocessed'
                WHERE id = ?
            """, (first_title[:150], first_text, existing[0]))

            upgraded += 1

        for index, (title, text) in enumerate(sections):

            cursor.execute("""
                INSERT OR IGNORE INTO context_items
                (source_id, section_index, type, title,
                 content, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                source_id,
                index,
                "source_section",
                title[:150],
                text,
                "unprocessed",
                timestamp()
            ))

            if cursor.rowcount > 0:
                extracted += 1

    db.commit()

    print("\nContext extraction complete.")
    print("New section records:", extracted)

    if upgraded:
        print("Older whole-document records split:", upgraded)
        print("Their existing links were kept; review them with :links.")

    print("Original content preserved.")

    # NEW IN 1.2: hand back the number of new records so :learn and
    # :update can report it. The command's own output is unchanged.
    return extracted


# ==========================================
# 9. CONTEXT CLASSIFICATION
# ==========================================

def classify_context(content):

    text = content.lower()

    if any(term in text for term in [
        "stands for", "refers to",
        "is defined as", "means ", "definition"
    ]):
        return "definition"

    if any(term in text for term in [
        "guiding principle", "core principle",
        "philosophy", "principle",
        "local context first"
    ]):
        return "principle"

    if any(term in text for term in [
        "we decided", "decision:",
        "agreed to", "selected approach"
    ]):
        return "decision"

    if any(term in text for term in [
        "must ", "should ", "required to",
        "do not ", "ensure that", "needs to "
    ]):
        return "instruction"

    if any(term in text for term in [
        "development milestone",
        "development roadmap",
        "future development",
        "version 0.",
        "initial development",
        "first milestone"
    ]):
        return "milestone"

    if any(term in text for term in [
        "relationship", "connected to",
        "links to", "depends on",
        "consists of", "composed of",
        "supplies experience",
        "processes experience"
    ]):
        return "relationship"

    return "general_context"


def classify_records():

    cursor.execute("""
        SELECT id, content
        FROM context_items
        ORDER BY id ASC
    """)

    records = cursor.fetchall()

    if not records:
        print("\nNothing to classify.")
        return

    for context_id, content in records:

        category = classify_context(content)

        cursor.execute("""
            UPDATE context_items
            SET type = ?, status = ?
            WHERE id = ?
        """, (
            category,
            "provisional",
            context_id
        ))

        print(f"Context {context_id}: {category}")

    db.commit()
    print("\nClassification complete.")


# ==========================================
# 10. RETRIEVE CONTEXT BODY
# ==========================================

def retrieve_context():

    cursor.execute("""
        SELECT id, source_id, section_index, type,
               title, content, status
        FROM context_items
        ORDER BY id ASC
    """)

    records = cursor.fetchall()

    if not records:
        print("\nContext Body is empty.")
        return

    print("\n========== CONTEXT BODY ==========")

    for record in records:
        print("\n----------------------------------")
        print("Context ID:", record[0])
        print("Source ID:", record[1], "| Section:", record[2])
        print("Type:", record[3])
        print("Title:", record[4])
        print("Status:", record[6])
        print("Content:")
        print(record[5])

    print("\n==================================")


# ==========================================
# 11. TEXT PROCESSING
# ==========================================

STOP_WORDS = {
    "the", "and", "for", "that", "this", "with",
    "from", "into", "about", "have", "has", "had",
    "are", "was", "were", "will", "would", "can",
    "could", "should", "must", "not", "but", "its",
    "their", "they", "them", "then", "than", "also",
    "been", "being", "you", "your", "our", "who",
    "what", "when", "where", "why", "how", "which",
    "while", "there", "here", "each", "all", "any",
    "some", "such", "only", "more", "most", "other",
    "these", "those", "both", "between", "within",
    "through", "using", "used", "use", "based", "per",
    "one", "two", "first", "second", "new", "same",
    "after", "before", "because", "during", "without",
    "does", "did", "done", "make", "made", "get",
    "got", "may", "might", "etc", "via", "own",
    "over", "under", "here", "very", "than", "has",

    # Short filler words. The term pattern accepts two-letter tokens
    # so that meaningful ones (iq, ai, ml, db) are kept; the filler
    # ones are listed here. Do NOT add real short terms to this list.
    "it", "to", "is", "of", "in", "on", "as", "at", "be", "by",
    "or", "an", "if", "so", "we", "do", "no", "up", "he", "me",
    "my", "us", "am", "go", "oh", "ok", "vs",

    # Common three-letter and other function words.
    "him", "his", "her", "she", "out", "off", "too", "now", "yet",
    "nor", "few", "many", "much", "just", "even", "still", "ever",
    "let", "lets", "say", "says", "said", "see", "seen", "put",
    "take", "takes", "taken", "give", "gives", "given", "like",
    "well", "back", "down", "again", "against", "among", "around",
    "else", "every", "either", "neither", "whether", "whose",
    "whom", "itself", "themselves", "yourself", "ourselves",
    "above", "below", "along", "across", "upon", "until", "since",
    "though", "although", "however", "therefore", "thus", "hence",
    "whenever", "wherever", "whatever", "whichever", "another"
}


def extract_terms(text):

    words = re.findall(
        r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,}",
        (text or "").lower()
    )

    return {
        word for word in words
        if word not in STOP_WORDS
        and not word.isdigit()
    }


# ==========================================
# 12. AUTOMATED ASSOCIATION
# ==========================================

def load_context_documents():

    cursor.execute("""
        SELECT id, title, content
        FROM context_items
        ORDER BY id ASC
    """)

    records = cursor.fetchall()
    documents = {}

    for context_id, title, content in records:

        combined = (
            (title or "")
            + "\n"
            + (content or "")
        )

        terms = extract_terms(combined)

        if terms:
            documents[context_id] = {
                "title": title or "Untitled",
                "content": content or "",
                "terms": terms,
                "text": combined.lower()
            }

    return documents


def calculate_document_frequencies(documents):

    frequencies = defaultdict(int)

    for document in documents.values():
        for term in document["terms"]:
            frequencies[term] += 1

    return frequencies


def calculate_similarity(
    first,
    second,
    frequencies,
    document_count
):

    shared = first["terms"] & second["terms"]

    if len(shared) < 2:
        return 0, [], 0

    def weight(term):
        return (
            math.log(
                (document_count + 1) /
                (frequencies[term] + 1)
            ) + 1
        )

    shared_weight = sum(
        weight(term) for term in shared
    )

    first_weight = sum(
        weight(term) for term in first["terms"]
    )

    second_weight = sum(
        weight(term) for term in second["terms"]
    )

    denominator = min(
        first_weight,
        second_weight
    )

    if denominator == 0:
        return 0, [], 0

    score = shared_weight / denominator

    evidence = sorted(
        shared,
        key=lambda term: weight(term),
        reverse=True
    )[:8]

    return score, evidence, len(shared)


def save_association(
    source_id,
    target_id,
    evidence,
    confidence
):

    cursor.execute("""
        INSERT OR IGNORE INTO context_links
        (
            source_context_id,
            relationship_type,
            target_context_id,
            status,
            created_at,
            evidence,
            confidence,
            method
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        source_id,
        "related_to",
        target_id,
        "provisional",
        timestamp(),
        ", ".join(evidence),
        round(confidence, 4),
        "automated_v0.5"
    ))

    return cursor.rowcount > 0


# ------------------------------------------
# 12A. ASSOCIATE A SPECIFIC TOPIC
# ------------------------------------------

def associate_topic(topic):

    topic = topic.strip()

    if not topic:
        print("Specify a topic to associate.")
        return

    documents = load_context_documents()

    if len(documents) < 2:
        print("At least two Context records are required.")
        return

    query_terms = extract_terms(topic)
    phrase = topic.lower()
    seeds = []

    for context_id, document in documents.items():

        if (
            phrase in document["text"]
            or (
                query_terms
                and query_terms.issubset(document["terms"])
            )
        ):
            seeds.append(context_id)

    if not seeds:
        print(f"\nNo Context records found for: {topic}")
        return

    frequencies = calculate_document_frequencies(documents)

    print("\n========== AUTOMATED ASSOCIATION ==========")
    print("Topic:", topic)
    print("Matching records:", len(seeds))

    created = 0
    examined = 0

    for seed_id in seeds:

        seed = documents[seed_id]

        print(
            f"\nSearching from Context {seed_id}: "
            f"{seed['title']}"
        )

        for target_id, target in documents.items():

            if target_id == seed_id:
                continue

            score, evidence, shared_count = calculate_similarity(
                seed,
                target,
                frequencies,
                len(documents)
            )

            examined += 1

            if shared_count < 2 or score < 0.15:
                continue

            was_created = save_association(
                seed_id,
                target_id,
                evidence,
                score
            )

            if was_created:
                created += 1
                print(
                    f"\nCandidate: {seed_id} "
                    f"--related_to--> {target_id}"
                )
                print("Target:", target["title"])
                print("Evidence:", ", ".join(evidence))
                print("Confidence:", round(score * 100, 1), "%")

    db.commit()

    print("\nAssociation search complete.")
    print("Comparisons:", examined)
    print("New relationships:", created)
    print("All new relationships are provisional.")

    # NEW IN 1.2: hand back the count (output unchanged).
    return created


# ------------------------------------------
# 12B. ASSOCIATE ALL CONTEXT RECORDS
# ------------------------------------------

def associate_all():

    documents = load_context_documents()

    if len(documents) < 2:
        print("At least two Context records are required.")
        return

    frequencies = calculate_document_frequencies(documents)
    inverted_index = defaultdict(list)

    for context_id, document in documents.items():
        for term in document["terms"]:
            inverted_index[term].append(context_id)

    pair_terms = defaultdict(set)

    for term, context_ids in inverted_index.items():
        for i in range(len(context_ids)):
            for j in range(i + 1, len(context_ids)):

                first_id = context_ids[i]
                second_id = context_ids[j]

                pair = (
                    min(first_id, second_id),
                    max(first_id, second_id)
                )

                pair_terms[pair].add(term)

    print("\n========== GLOBAL ASSOCIATION ==========")
    print("Context records:", len(documents))
    print("Candidate pairs:", len(pair_terms))

    created = 0
    examined = 0

    for (first_id, second_id) in pair_terms:

        first = documents[first_id]
        second = documents[second_id]

        score, evidence, shared_count = calculate_similarity(
            first,
            second,
            frequencies,
            len(documents)
        )

        examined += 1

        if shared_count < 2 or score < 0.15:
            continue

        was_created = save_association(
            first_id,
            second_id,
            evidence,
            score
        )

        if was_created:
            created += 1
            print(f"\n{first_id} --related_to--> {second_id}")
            print(first["title"], "<->", second["title"])
            print("Evidence:", ", ".join(evidence))
            print("Confidence:", round(score * 100, 1), "%")

    db.commit()

    print("\nGlobal association complete.")
    print("Pairs examined:", examined)
    print("New relationships:", created)
    print("All new relationships are provisional.")

    # NEW IN 1.2: hand back the count (output unchanged).
    return created


# ==========================================
# 13. MANUAL CONTEXT RELATIONSHIP
# ==========================================

def create_link(source_id, relation, target_id):

    try:
        source_id = int(source_id)
        target_id = int(target_id)

    except ValueError:
        print("Context IDs must be numbers.")
        return

    if source_id == target_id:
        print("A record cannot link to itself.")
        return

    relation = relation.strip().lower()
    relation = re.sub(r"\s+", "_", relation)

    if not re.fullmatch(r"[a-z][a-z0-9_]*", relation):
        print("Invalid relationship name.")
        return

    cursor.execute("""
        SELECT id FROM context_items
        WHERE id IN (?, ?)
    """, (source_id, target_id))

    existing = {row[0] for row in cursor.fetchall()}

    if source_id not in existing:
        print("Source Context ID does not exist.")
        return

    if target_id not in existing:
        print("Target Context ID does not exist.")
        return

    cursor.execute("""
        INSERT OR IGNORE INTO context_links
        (
            source_context_id,
            relationship_type,
            target_context_id,
            status,
            created_at,
            method
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        source_id,
        relation,
        target_id,
        "provisional",
        timestamp(),
        "manual"
    ))

    db.commit()

    if cursor.rowcount > 0:
        print("\nRelationship created.")
    else:
        print("\nThis relationship already exists.")

    print(f"{source_id} --{relation}--> {target_id}")


# ==========================================
# 14. VIEW CONTEXT RELATIONSHIPS
# ==========================================

def retrieve_links():

    cursor.execute("""
        SELECT
            l.id,
            l.source_context_id,
            s.title,
            l.relationship_type,
            l.target_context_id,
            t.title,
            l.status,
            l.created_at,
            l.evidence,
            l.confidence,
            l.method
        FROM context_links AS l
        LEFT JOIN context_items AS s
            ON l.source_context_id = s.id
        LEFT JOIN context_items AS t
            ON l.target_context_id = t.id
        ORDER BY l.id ASC
    """)

    records = cursor.fetchall()

    if not records:
        print("\nNo context relationships stored yet.")
        return

    print("\n======= CONTEXT RELATIONSHIPS =======")

    for record in records:
        print("\n----------------------------------")
        print("Link ID:", record[0])

        print(
            f"{record[1]} ({record[2]})"
            f" --{record[3]}--> "
            f"{record[4]} ({record[5]})"
        )

        print("Status:", record[6])
        print("Created:", record[7])
        print("Evidence:", record[8] or "Not recorded")

        if record[9] is not None:
            print("Confidence:", round(record[9] * 100, 1), "%")

        print("Method:", record[10] or "Manual/legacy")

    print("\n=====================================")


# ==========================================
# 15. VALIDATE A RELATIONSHIP
# ==========================================

def update_link_status(link_id, new_status):

    try:
        link_id = int(link_id)

    except ValueError:
        print("Link ID must be a number.")
        return

    cursor.execute("""
        UPDATE context_links
        SET status = ?
        WHERE id = ?
    """, (new_status, link_id))

    db.commit()

    if cursor.rowcount > 0:
        print(f"Link {link_id} status: {new_status}")
    else:
        print("Relationship not found.")


# ==========================================
# 16. RELATIONSHIP-AWARE KNOWLEDGE RETRIEVAL
# ==========================================

def make_excerpt(content, terms, limit=900):

    content = content or ""

    if len(content) <= limit:
        return content

    lower = content.lower()

    positions = [
        lower.find(term.lower())
        for term in terms
        if lower.find(term.lower()) >= 0
    ]

    start = 0

    if positions:
        start = max(
            0,
            min(positions) - limit // 4
        )

    end = min(len(content), start + limit)
    excerpt = content[start:end]

    if start > 0:
        excerpt = "... " + excerpt

    if end < len(content):
        excerpt += " ..."

    return excerpt


# ------------------------------------------
# 16A. FIND RELATIONSHIPS
# ------------------------------------------

def find_retrieval_links(context_ids, statuses):

    if not context_ids or not statuses:
        return []

    id_marks = ",".join(["?"] * len(context_ids))
    status_marks = ",".join(["?"] * len(statuses))

    sql = f"""
        SELECT
            l.id,
            l.source_context_id,
            s.title,
            l.relationship_type,
            l.target_context_id,
            t.title,
            l.status,
            l.evidence,
            l.confidence
        FROM context_links AS l
        LEFT JOIN context_items AS s
            ON l.source_context_id = s.id
        LEFT JOIN context_items AS t
            ON l.target_context_id = t.id
        WHERE (
            l.source_context_id IN ({id_marks})
            OR
            l.target_context_id IN ({id_marks})
        )
        AND l.status IN ({status_marks})
    """

    parameters = context_ids + context_ids + statuses
    cursor.execute(sql, parameters)

    return cursor.fetchall()


# ------------------------------------------
# 16B. SCORE A CONTEXT RECORD AGAINST A QUERY
# ------------------------------------------

def score_context_record(
    document,
    query_text,
    query_terms,
    query_weights,
    total_query_weight
):

    shared = query_terms & document["terms"]

    phrase_match = (
        query_text in document["text"]
        if len(query_text) >= 3
        else False
    )

    if not shared and not phrase_match:
        return None

    shared_weight = sum(
        query_weights[term]
        for term in shared
    )

    if total_query_weight:
        coverage = shared_weight / total_query_weight
    else:
        coverage = 0

    title_terms = (
        extract_terms(document["title"]) & query_terms
    )

    title_bonus = (
        0.12 * len(title_terms)
        / max(1, len(query_terms))
    )

    phrase_bonus = 0.20 if phrase_match else 0

    score = min(
        1.0,
        coverage + title_bonus + phrase_bonus
    )

    return {
        "score": score,
        "shared": shared,
        "phrase_match": phrase_match
    }


# ------------------------------------------
# 16C. RANK UNIQUE CONNECTED CONTEXT RECORDS
# ------------------------------------------

def rank_related_records(
    links,
    direct_matches,
    documents,
    query_text,
    query_terms,
    query_weights,
    total_query_weight
):

    direct_by_id = {
        item["id"]: item
        for item in direct_matches
    }

    related_by_id = {}
    direct_relationships = []

    for link in links:

        (
            link_id,
            source_id,
            source_title,
            relation,
            target_id,
            target_title,
            status,
            evidence,
            confidence
        ) = link

        source_is_direct = source_id in direct_by_id
        target_is_direct = target_id in direct_by_id

        if source_is_direct and target_is_direct:
            direct_relationships.append(link)
            continue

        if source_is_direct:
            direct_id = source_id
            related_id = target_id

        elif target_is_direct:
            direct_id = target_id
            related_id = source_id

        else:
            continue

        if related_id in direct_by_id:
            continue

        document = documents.get(related_id)

        if document is None:
            continue

        relevance = score_context_record(
            document,
            query_text,
            query_terms,
            query_weights,
            total_query_weight
        )

        if relevance is None:
            related_relevance = 0.0
            shared_terms = set()

        else:
            related_relevance = relevance["score"]
            shared_terms = relevance["shared"]

        try:
            link_confidence = float(confidence or 0)

        except (TypeError, ValueError):
            link_confidence = 0.0

        link_confidence = max(
            0.0,
            min(1.0, link_confidence)
        )

        evidence_terms = extract_terms(evidence or "")

        evidence_relevance = (
            len(evidence_terms & query_terms)
            / max(1, len(query_terms))
        )

        source_relevance = direct_by_id[direct_id]["score"]

        retrieval_score = (
            0.45 * source_relevance
            + 0.35 * related_relevance
            + 0.15 * link_confidence
            + 0.05 * evidence_relevance
        )

        path = {
            "link_id": link_id,
            "source_id": source_id,
            "source_title": source_title or "Untitled",
            "relation": relation,
            "target_id": target_id,
            "target_title": target_title or "Untitled",
            "status": status,
            "evidence": evidence,
            "confidence": link_confidence,
            "direct_id": direct_id
        }

        if related_id not in related_by_id:

            related_by_id[related_id] = {
                "id": related_id,
                "title": document["title"],
                "content": document["content"],
                "terms": document["terms"],
                "shared": shared_terms,
                "score": retrieval_score,
                "paths": [path]
            }

        else:
            candidate = related_by_id[related_id]
            candidate["paths"].append(path)

            if retrieval_score > candidate["score"]:
                candidate["score"] = retrieval_score
                candidate["shared"] = shared_terms

            candidate["shared"] = (
                candidate["shared"] | shared_terms
            )

    related_records = sorted(
        related_by_id.values(),
        key=lambda item: item["score"],
        reverse=True
    )

    return related_records, direct_relationships


# ------------------------------------------
# 16D. DISPLAY CONNECTED KNOWLEDGE
# ------------------------------------------

def display_related_records(records, limit=8):

    print("\nRELATIONSHIP-CONNECTED KNOWLEDGE")
    print("Unique related records:", len(records))

    if not records:
        print("No additional connected records found.")
        return

    for item in records[:limit]:

        print("\n----------------------------------")
        print("Context ID:", item["id"])
        print("Title:", item["title"])

        print(
            "Retrieval rank:",
            round(item["score"] * 100, 1), "%"
        )

        if item["shared"]:
            print(
                "Query terms also present:",
                ", ".join(sorted(item["shared"]))
            )

        print("Relationship paths:")

        shown_paths = item["paths"][:3]

        for path in shown_paths:
            print(
                f"  Context {path['source_id']} "
                f"--{path['relation']}--> "
                f"Context {path['target_id']} "
                f"[{path['status']}]"
            )

        if len(item["paths"]) > len(shown_paths):
            print(
                "  Additional paths:",
                len(item["paths"]) - len(shown_paths)
            )

        print("Content:")

        print(
            make_excerpt(
                item["content"],
                list(item["shared"]),
                900
            )
        )

    if len(records) > limit:
        print(
            f"\n{len(records) - limit} more unique related "
            "records not displayed."
        )


def display_direct_relationships(records, limit=10):

    print("\nRELATIONSHIPS BETWEEN DIRECT MATCHES")

    if not records:
        print("No direct links between the matching records.")
        return

    print("Direct relationships:", len(records))

    for record in records[:limit]:

        (
            link_id,
            source_id,
            source_title,
            relation,
            target_id,
            target_title,
            status,
            evidence,
            confidence
        ) = record

        print(
            f"Context {source_id} ({source_title}) "
            f"--{relation}--> "
            f"Context {target_id} ({target_title}) "
            f"[{status}]"
        )

    if len(records) > limit:
        print(
            f"{len(records) - limit} additional "
            "direct relationships omitted."
        )


# ------------------------------------------
# 16E. SEARCH CONTENT NOT YET EXTRACTED
# ------------------------------------------

def search_unextracted_content(query, query_terms):

    sql = f"""
        SELECT
            c.{quote(id_col)},
            c.{quote(content_col)}
        FROM content_items AS c
        LEFT JOIN context_items AS x
            ON x.source_id = c.{quote(id_col)}
        WHERE x.id IS NULL
        ORDER BY c.{quote(id_col)} DESC
    """

    cursor.execute(sql)
    records = cursor.fetchall()
    matches = []

    for record_id, content in records:

        terms = extract_terms(content)
        shared = query_terms & terms

        phrase_match = (
            query.lower() in (content or "").lower()
        )

        if shared or phrase_match:

            score = (
                len(shared) / max(1, len(query_terms))
            )

            if phrase_match:
                score += 0.2

            matches.append(
                (score, record_id, content, shared)
            )

    matches.sort(
        key=lambda item: item[0],
        reverse=True
    )

    if not matches:
        return

    print("\nUNEXTRACTED CONTENT MATCHES")

    for score, record_id, content, shared in matches[:5]:

        print("\n----------------------------------")
        print("Content ID:", record_id)
        print("Relevance:", round(score * 100, 1), "%")
        print("Matching terms:", ", ".join(sorted(shared)))

        print(
            make_excerpt(
                content,
                list(shared),
                900
            )
        )


# ------------------------------------------
# 16F. MAIN KNOWLEDGE RETRIEVAL
# ------------------------------------------

def retrieve_knowledge(query=None):

    if not query:
        query = input(
            "\nWhat should BRAIN retrieve? "
        ).strip()

    if not query:
        print("No search query supplied.")
        return

    query_text = re.sub(
        r"\s+",
        " ",
        query.lower()
    ).strip()

    query_terms = extract_terms(query)

    # Search stored synthesized knowledge first.
    search_knowledge_body(query_text)

    documents = load_context_documents()

    if not documents:
        print("\nContext Body is empty.")
        search_unextracted_content(
            query_text,
            query_terms
        )
        return

    frequencies = calculate_document_frequencies(documents)
    document_count = len(documents)
    query_weights = {}

    for term in query_terms:

        frequency = frequencies.get(term, 0)

        query_weights[term] = (
            math.log(
                (document_count + 1) /
                (frequency + 1)
            ) + 1
        )

    total_query_weight = sum(query_weights.values())
    matches = []

    for context_id, document in documents.items():

        relevance = score_context_record(
            document,
            query_text,
            query_terms,
            query_weights,
            total_query_weight
        )

        if relevance is None:
            continue

        matches.append({
            "id": context_id,
            "title": document["title"],
            "content": document["content"],
            "shared": relevance["shared"],
            "score": relevance["score"]
        })

    matches.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    if not matches:
        print(f"\nNo Context matches found for: {query}")

        search_unextracted_content(
            query_text,
            query_terms
        )
        return

    print("\n========== BRAIN RETRIEVAL ==========")
    print("Search:", query)
    print("Direct matches:", len(matches))

    for item in matches[:8]:

        print("\n----------------------------------")
        print("Context ID:", item["id"])
        print("Title:", item["title"])
        print("Matching terms:", ", ".join(sorted(item["shared"])))

        print(
            "Relevance score:",
            round(item["score"] * 100, 1), "%"
        )

        print("Original content:")

        print(
            make_excerpt(
                item["content"],
                list(item["shared"]),
                1200
            )
        )

    direct_ids = [
        item["id"] for item in matches
    ]

    established_links = find_retrieval_links(
        direct_ids,
        ["established"]
    )

    provisional_links = find_retrieval_links(
        direct_ids,
        ["provisional"]
    )

    all_links = established_links + provisional_links

    related_records, direct_relationships = rank_related_records(
        all_links,
        matches,
        documents,
        query_text,
        query_terms,
        query_weights,
        total_query_weight
    )

    display_direct_relationships(direct_relationships)
    display_related_records(related_records)

    search_unextracted_content(
        query_text,
        query_terms
    )

    print("\n========== RETRIEVAL SUMMARY ==========")
    print("Direct matches:", len(matches))
    print("Established relationships:", len(established_links))
    print("Provisional relationships:", len(provisional_links))
    print("Unique connected records:", len(related_records))
    print("Direct-to-direct relationships:", len(direct_relationships))
    print("=======================================")


# ==========================================
# 17. KNOWLEDGE ACQUISITION: EVIDENCE DIGEST
# ==========================================
# An evidence digest is built by EXTRACTION. It selects the most
# relevant sentences from the Context records, keeps them verbatim,
# and groups them by source so nothing is mixed or reworded. It is
# bounded in size. It does not claim to be an original synthesis; an
# LLM can write one from this digest, with provenance already attached.

MAX_DIGEST_SENTENCES = 10
MAX_DIGEST_CHARS = 1800
MAX_SENTENCES_PER_SOURCE = 3
MAX_SENTENCES_PER_LINKED_SOURCE = 2
MAX_SELECTED_SOURCES = 12
MAX_DIRECT_SOURCES = 8
MIN_LINK_CONFIDENCE = 0.25

# Sentences starting with these words depend on the sentence before them.
PRONOUN_START = re.compile(
    r"^(this|that|these|those|it|its|they|their|"
    r"he|she|his|her|such)\b",
    re.IGNORECASE
)


# ------------------------------------------
# 17A. SELECT RELEVANT CONTEXT RECORDS
# ------------------------------------------

def select_synthesis_sources(query):

    documents = load_context_documents()

    if not documents:
        return [], {}, {}

    query_text = re.sub(
        r"\s+",
        " ",
        query.lower()
    ).strip()

    query_terms = extract_terms(query)

    if not query_terms:
        return [], documents, {}

    frequencies = calculate_document_frequencies(documents)
    document_count = len(documents)

    query_weights = {}

    for term in query_terms:
        frequency = frequencies.get(term, 0)

        query_weights[term] = (
            math.log(
                (document_count + 1) /
                (frequency + 1)
            ) + 1
        )

    total_query_weight = sum(query_weights.values())

    matches = []

    for context_id, document in documents.items():

        relevance = score_context_record(
            document,
            query_text,
            query_terms,
            query_weights,
            total_query_weight
        )

        if relevance is None:
            continue

        matches.append({
            "id": context_id,
            "title": document["title"],
            "content": document["content"],
            "terms": document["terms"],
            "score": relevance["score"],
            "shared": relevance["shared"],
            "via_link": None,
            "via_terms": set()
        })

    if not matches:
        return [], documents, query_weights

    matches.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    # Keep records with meaningful relevance to the topic.
    highest_score = matches[0]["score"]
    minimum_score = max(0.08, highest_score * 0.20)

    selected = [
        item for item in matches
        if item["score"] >= minimum_score
    ][:MAX_DIRECT_SOURCES]

    selected_ids = {item["id"] for item in selected}

    # Pull in records connected to the direct matches by a relationship
    # even when they use different wording. A connected record
    # qualifies when its link is established (or provisional with
    # enough confidence) and it contains at least two of the terms the
    # link itself was built on. Those bridging terms, not the query
    # terms, are then used to pick its sentences.
    links = find_retrieval_links(
        list(selected_ids),
        ["established", "provisional"]
    )

    bridges = {}

    for link in links:

        (
            link_id,
            source_id,
            _source_title,
            _relation,
            target_id,
            _target_title,
            status,
            evidence,
            confidence
        ) = link

        if source_id in selected_ids and target_id not in selected_ids:
            connected_id = target_id

        elif target_id in selected_ids and source_id not in selected_ids:
            connected_id = source_id

        else:
            continue

        try:
            confidence = float(confidence or 0)

        except (TypeError, ValueError):
            confidence = 0.0

        if status != "established" and confidence < MIN_LINK_CONFIDENCE:
            continue

        document = documents.get(connected_id)

        if document is None:
            continue

        usable = extract_terms(evidence or "") & document["terms"]

        if len(usable) < 2:
            continue

        strength = 1.0 if status == "established" else confidence

        entry = bridges.setdefault(
            connected_id,
            {"terms": set(), "strength": 0.0, "link_id": link_id}
        )

        entry["terms"] |= usable

        if strength > entry["strength"]:
            entry["strength"] = strength
            entry["link_id"] = link_id

    ranked_bridges = sorted(
        bridges.items(),
        key=lambda pair: pair[1]["strength"],
        reverse=True
    )

    for connected_id, bridge in ranked_bridges:

        if len(selected) >= MAX_SELECTED_SOURCES:
            break

        document = documents[connected_id]

        selected.append({
            "id": connected_id,
            "title": document["title"],
            "content": document["content"],
            "terms": document["terms"],
            "score": None,
            "shared": set(),
            "via_link": bridge["link_id"],
            "via_terms": bridge["terms"]
        })

    return selected, documents, query_weights


# ------------------------------------------
# 17B. SPLIT INTO SENTENCES
# ------------------------------------------

def split_sentences(content):

    content = (content or "").replace("\r", "\n")

    pieces = re.split(
        r"(?<=[.!?])\s+|\n+",
        content
    )

    sentences = []

    for piece in pieces:

        sentence = piece.strip()
        sentence = re.sub(r"^[\s\-*•#\d.)]+", "", sentence)

        if len(sentence) < 8:
            continue

        if not extract_terms(sentence):
            continue

        sentences.append(sentence)

    return sentences


# ------------------------------------------
# 17C. BUILD THE EVIDENCE DIGEST
# ------------------------------------------

def build_synthesis(query, selected_sources, query_weights):

    query_terms = extract_terms(query)
    seen = set()
    per_source = []

    for source in selected_sources:

        if source.get("via_link") is None:
            match_terms = query_terms
            weights = query_weights
            cap = MAX_SENTENCES_PER_SOURCE

        else:
            match_terms = source["via_terms"]
            weights = {term: 1.0 for term in match_terms}
            cap = MAX_SENTENCES_PER_LINKED_SOURCE

        weight_total = sum(weights.values()) or 1.0
        sentences = split_sentences(source["content"])
        candidates = []

        for index, sentence in enumerate(sentences):

            shared = extract_terms(sentence) & match_terms

            if not shared:
                continue

            normalized = " ".join(
                re.findall(r"[a-z0-9]+", sentence.lower())
            )

            if normalized in seen:
                continue

            seen.add(normalized)

            candidates.append({
                "sentence": sentence,
                "context_id": source["id"],
                "source_title": source["title"],
                "index": index,
                "score": (
                    sum(weights.get(term, 1.0) for term in shared)
                    / weight_total
                ),
                "lead_in": False,
                "via": source.get("via_link")
            })

        candidates.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        per_source.append(
            (source, sentences, candidates[:cap])
        )

    # Take each source's best sentence first so several sources are
    # represented, then fill the remaining room by relevance.
    first_choices = [
        chosen[0] for _, _, chosen in per_source if chosen
    ]

    remainder = [
        item
        for _, _, chosen in per_source
        for item in chosen[1:]
    ]

    remainder.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    picked = []
    used_chars = 0

    for candidate in first_choices + remainder:

        if len(picked) >= MAX_DIGEST_SENTENCES:
            break

        size = len(candidate["sentence"])

        if picked and used_chars + size > MAX_DIGEST_CHARS:
            continue

        picked.append(candidate)
        used_chars += size

    # A sentence that opens with "This", "It", "They" etc. is
    # meaningless alone, so keep the sentence before it.
    picked_keys = {
        (item["context_id"], item["index"]) for item in picked
    }

    sentence_lookup = {
        source["id"]: sentences
        for source, sentences, _ in per_source
    }

    for candidate in list(picked):

        index = candidate["index"]
        key = (candidate["context_id"], index - 1)

        if (
            index > 0
            and key not in picked_keys
            and PRONOUN_START.match(candidate["sentence"])
        ):
            previous = sentence_lookup[candidate["context_id"]][index - 1]

            picked.append({
                "sentence": previous,
                "context_id": candidate["context_id"],
                "source_title": candidate["source_title"],
                "index": index - 1,
                "score": 0.0,
                "lead_in": True,
                "via": candidate["via"]
            })

            picked_keys.add(key)

    contributing = {
        item["context_id"] for item in picked
        if not item["lead_in"]
    }

    if len(contributing) < 2 or len(picked) < 2:
        return None

    source_order = {
        source["id"]: position
        for position, source in enumerate(selected_sources)
    }

    by_source = defaultdict(list)

    for item in picked:
        by_source[item["context_id"]].append(item)

    blocks = []

    for context_id in sorted(by_source, key=lambda sid: source_order[sid]):

        items = sorted(
            by_source[context_id],
            key=lambda item: item["index"]
        )

        header = f"[Context {context_id}] {items[0]['source_title']}"

        if items[0]["via"] is not None:
            header += f" (connected via relationship {items[0]['via']})"

        lines = [header] + ["- " + item["sentence"] for item in items]
        blocks.append("\n".join(lines))

    title_query = re.sub(r"^[\s?]+|[\s?]+$", "", query)[:125].strip()
    title = "Evidence digest: " + title_query

    body = (
        f"Evidence digest from {len(contributing)} Context records. "
        "Extractive: sentences are quoted verbatim, grouped by "
        "source, and not rewritten.\n\n"
        + "\n\n".join(blocks)
    )

    return {
        "title": title[:150],
        "content": body,
        "source_ids": contributing,
        "sentences": picked
    }


# ------------------------------------------
# 17D. STORE DIGEST AND SOURCE PROVENANCE
# ------------------------------------------

def save_knowledge_synthesis(
    synthesis,
    selected_sources
):

    title = synthesis["title"]
    content = synthesis["content"]

    content_hash = hashlib.sha256(
        (title + "\n" + content).encode("utf-8")
    ).hexdigest()

    now = timestamp()

    cursor.execute("""
        INSERT OR IGNORE INTO knowledge_items
        (
            title,
            content,
            status,
            created_at,
            method,
            source_count,
            content_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        title,
        content,
        "provisional",
        now,
        "local_extractive_digest_v0.9",
        len(synthesis["source_ids"]),
        content_hash
    ))

    db.commit()

    cursor.execute("""
        SELECT id
        FROM knowledge_items
        WHERE content_hash = ?
    """, (content_hash,))

    result = cursor.fetchone()

    if not result:
        raise RuntimeError(
            "Evidence digest could not be stored."
        )

    knowledge_id = result[0]

    source_lookup = {
        item["id"]: item
        for item in selected_sources
    }

    for source_id in synthesis["source_ids"]:

        source = source_lookup.get(source_id)

        # Records included through a relationship have no query
        # relevance score, so none is stored for them.
        relevance = source["score"] if source is not None else None

        source_rank = (
            selected_sources.index(source) + 1
            if source is not None
            else None
        )

        cursor.execute("""
            INSERT OR IGNORE INTO knowledge_sources
            (
                knowledge_id,
                context_id,
                source_rank,
                relevance,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            knowledge_id,
            source_id,
            source_rank,
            relevance,
            now
        ))

    cursor.execute("""
        SELECT COUNT(*)
        FROM knowledge_sources
        WHERE knowledge_id = ?
    """, (knowledge_id,))

    source_count = cursor.fetchone()[0]

    cursor.execute("""
        UPDATE knowledge_items
        SET source_count = ?
        WHERE id = ?
    """, (
        source_count,
        knowledge_id
    ))

    db.commit()

    return knowledge_id, source_count


# ------------------------------------------
# 17E. RUN THE DIGEST
# ------------------------------------------

def synthesize_knowledge(query=None):

    if not query:
        query = input(
            "\nWhat topic should BRAIN build an evidence digest for? "
        ).strip()

    if not query:
        print("No topic supplied.")
        return

    selected_sources, documents, query_weights = (
        select_synthesis_sources(query)
    )

    if len(selected_sources) < 2:

        print("\nInsufficient source knowledge for a digest.")
        print("At least two relevant Context records are required.")
        print("Tip: run :extract so long content is split into sections.")
        return

    synthesis = build_synthesis(
        query,
        selected_sources,
        query_weights
    )

    if synthesis is None:

        print("\nNo multi-source digest could be composed.")
        print("The selected records did not provide enough distinct evidence.")
        return

    print("\n========== EVIDENCE DIGEST ==========")
    print("Topic:", query)
    print("Candidate Context records:", len(selected_sources))
    print("Contributing Context records:", len(synthesis["source_ids"]))
    print("Sentences included:", len(synthesis["sentences"]))

    print("\nDIGEST")
    print("-----------------------------------------")
    print(synthesis["title"])
    print()
    print(synthesis["content"])

    knowledge_id, source_count = save_knowledge_synthesis(
        synthesis,
        selected_sources
    )

    # UPDATED IN 1.1: show the item's REAL status. An identical digest
    # that already exists keeps the status it was given, including a
    # rejection, so nothing is silently reset to "provisional".
    cursor.execute(
        "SELECT status FROM knowledge_items WHERE id = ?",
        (knowledge_id,)
    )

    stored_status = cursor.fetchone()[0]

    print("\nDIGEST STORED")
    print("Knowledge ID:", knowledge_id)
    print("Knowledge status:", stored_status)

    if stored_status == "rejected":
        print("Note: this identical digest was rejected earlier and")
        print("stays rejected. Use :confirm knowledge", knowledge_id,
              "to restore it.")

    elif stored_status == "established":
        print("Note: this identical digest is already confirmed.")

    elif stored_status == "supported":
        print("Note: this identical digest is already system-checked.")

    print("Source records preserved:", source_count)
    print("Method: local extractive digest")
    print("=========================================")

    # NEW IN 1.2: hand back the stored item's ID so :learn can check it.
    return knowledge_id


# ==========================================
# 18. KNOWLEDGE BODY RETRIEVAL
# ==========================================

# ------------------------------------------
# 18A. DISPLAY SOURCE PROVENANCE
# ------------------------------------------

def display_knowledge_sources(knowledge_id):

    cursor.execute("""
        SELECT
            ks.context_id,
            ks.source_rank,
            ks.relevance,
            c.source_id,
            c.section_index,
            c.title
        FROM knowledge_sources AS ks
        JOIN context_items AS c
            ON ks.context_id = c.id
        WHERE ks.knowledge_id = ?
        ORDER BY ks.source_rank ASC, ks.context_id ASC
    """, (knowledge_id,))

    sources = cursor.fetchall()

    print("\nSOURCE PROVENANCE")

    if not sources:
        print("No source records linked.")
        return

    for source in sources:

        context_id, rank, relevance, content_id, section, title = source

        print(
            f"Context {context_id} | "
            f"Content {content_id} (section {section}) | "
            f"{title}"
        )

        if relevance is not None:
            print(
                "  Source relevance:",
                round(relevance * 100, 1),
                "%"
            )

        else:
            print("  Included through a relationship")


# ------------------------------------------
# 18B. VIEW KNOWLEDGE BODY
# ------------------------------------------

def retrieve_knowledge_body():

    cursor.execute("""
        SELECT
            id,
            title,
            content,
            status,
            created_at,
            method,
            source_count,
            reviewed_at,
            checked_at,
            check_notes
        FROM knowledge_items
        ORDER BY id ASC
    """)

    records = cursor.fetchall()

    if not records:
        print("\nKnowledge Body is empty.")
        return

    print("\n========== KNOWLEDGE BODY ==========")

    for record in records:

        (
            knowledge_id,
            title,
            content,
            status,
            created_at,
            method,
            source_count,
            reviewed_at,
            checked_at,
            check_notes
        ) = record

        print("\n----------------------------------")
        print("Knowledge ID:", knowledge_id)
        print("Title:", title)
        print("Status:", status)
        print("Created:", created_at)
        print("Method:", method)
        print("Source count:", source_count)

        # NEW IN 1.1: shown only for items that have been reviewed.
        if reviewed_at:
            print("Reviewed:", reviewed_at)

        # NEW IN 1.2: when BRAIN last ran its automatic checks, and what
        # each rule found.
        if checked_at:
            print("Checked:", checked_at)

            for note in (check_notes or "").split(" | "):
                print("  Check -", note)

        print("\nKnowledge:")
        print(content)

        display_knowledge_sources(knowledge_id)

    print("\n====================================")


# ------------------------------------------
# 18C. SEARCH STORED KNOWLEDGE
# ------------------------------------------

def search_knowledge_body(query):

    query_terms = extract_terms(query)

    if not query_terms:
        return

    cursor.execute("""
        SELECT id, title, content, status, source_count
        FROM knowledge_items
        ORDER BY id DESC
    """)

    records = cursor.fetchall()

    if not records:
        return

    matches = []

    # NEW IN 1.1: counts rejected items that matched, so they can be
    # skipped from the results but the person is still told.
    rejected_hidden = 0

    for knowledge_id, title, content, status, source_count in records:

        combined = (
            (title or "")
            + "\n"
            + (content or "")
        )

        terms = extract_terms(combined)
        shared = query_terms & terms

        phrase_match = (
            query.lower() in combined.lower()
        )

        if not shared and not phrase_match:
            continue

        # NEW IN 1.1: rejected knowledge stays stored but is not
        # returned by :retrieve.
        if status == "rejected":
            rejected_hidden += 1
            continue

        relevance = (
            len(shared) / max(1, len(query_terms))
        )

        if phrase_match:
            relevance += 0.20

        matches.append({
            "id": knowledge_id,
            "title": title,
            "content": content,
            "status": status,
            "source_count": source_count,
            "shared": shared,
            "score": relevance
        })

    if not matches:

        # NEW IN 1.1: say so when the only matches were rejected ones.
        if rejected_hidden:
            print(
                f"\n{rejected_hidden} rejected knowledge item(s) "
                "matched but are hidden. See :knowledge."
            )

        return

    matches.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    print("\n========== SAVED KNOWLEDGE MATCHES ==========")

    for item in matches[:5]:

        print("\n----------------------------------")
        print("Knowledge ID:", item["id"])
        print("Title:", item["title"])
        print("Status:", item["status"])

        # NEW IN 1.2: make clear that "supported" is BRAIN's own check.
        if item["status"] == "supported":
            print("  (system-checked; not yet confirmed by you)")

        print("Relevance:", round(item["score"] * 100, 1), "%")
        print("Source count:", item["source_count"])
        print("Matching terms:", ", ".join(sorted(item["shared"])))
        print("\nStored knowledge:")
        print(item["content"])

        display_knowledge_sources(item["id"])

    # NEW IN 1.1: same note when some matches were shown and some hidden.
    if rejected_hidden:
        print(
            f"\n{rejected_hidden} rejected knowledge item(s) "
            "matched but are hidden. See :knowledge."
        )

    print("\n=============================================")


# ------------------------------------------
# 18D. REVIEW KNOWLEDGE (NEW IN 1.1)
# ------------------------------------------
# Marks a Knowledge Body item "established" (confirmed) or "rejected".
# This mirrors how relationships are reviewed with :confirm/:reject.
# A rejected item is NEVER deleted: it stays stored with the date of
# the review, is hidden from :retrieve, and still shows in :knowledge.
# Rejecting is reversible, because confirming a rejected item
# restores it. Because the stored digest is unchanged, rebuilding an
# identical digest later finds it already on record and leaves its
# status alone.
def review_knowledge(knowledge_id, new_status):

    try:
        knowledge_id = int(knowledge_id)

    except ValueError:
        print("Knowledge ID must be a number.")
        return

    cursor.execute("""
        SELECT title, status
        FROM knowledge_items
        WHERE id = ?
    """, (knowledge_id,))

    record = cursor.fetchone()

    if record is None:
        print("Knowledge item not found. See :knowledge for IDs.")
        return

    title, old_status = record

    if old_status == new_status:
        print(f"Knowledge {knowledge_id} is already {new_status}.")
        return

    cursor.execute("""
        UPDATE knowledge_items
        SET status = ?, reviewed_at = ?
        WHERE id = ?
    """, (new_status, timestamp(), knowledge_id))

    db.commit()

    print(f"\nKnowledge {knowledge_id}: {title}")
    print(f"Status: {old_status} -> {new_status}")

    if new_status == "rejected":
        print("Kept on record; hidden from :retrieve.")
        print(f"To restore it: :confirm knowledge {knowledge_id}")


# ------------------------------------------
# 18E. AUTOMATIC SUPPORT CHECK (NEW IN 1.2)
# ------------------------------------------
# BRAIN can now judge a digest against written rules, but it only ever
# reaches "supported" (system-checked). "established" stays yours:
# BRAIN never sets it, and never changes a status you set
# (established or rejected). A supported digest that later fails the
# rules goes back to provisional, because that earlier call was
# BRAIN's own to take back.
#
# What a pass means: the digest is well sourced, faithful to its
# sources and not tied to anything you rejected. It does NOT mean the
# content is true; only you can vouch for that.

SUPPORT_MIN_SOURCES = 3
SUPPORT_MIN_CONTENT_ITEMS = 2


# Runs the three rules on one digest and returns (passed, results),
# where results is a list of (rule, ok, detail). Nothing is written.
def evaluate_knowledge(knowledge_id):

    cursor.execute("""
        SELECT content
        FROM knowledge_items
        WHERE id = ?
    """, (knowledge_id,))

    row = cursor.fetchone()

    if row is None:
        return None

    digest_text = row[0] or ""

    cursor.execute("""
        SELECT ks.context_id, c.source_id, c.content
        FROM knowledge_sources AS ks
        JOIN context_items AS c
            ON c.id = ks.context_id
        WHERE ks.knowledge_id = ?
    """, (knowledge_id,))

    sources = cursor.fetchall()
    context_ids = [source[0] for source in sources]
    content_ids = {source[1] for source in sources}
    results = []

    # Rule 1 - breadth: enough source records, from more than one
    # original piece of content, so one document cannot carry it alone.
    enough = (
        len(sources) >= SUPPORT_MIN_SOURCES
        and len(content_ids) >= SUPPORT_MIN_CONTENT_ITEMS
    )

    results.append((
        "breadth",
        enough,
        f"{len(sources)} source record(s) from "
        f"{len(content_ids)} content item(s); needs "
        f"{SUPPORT_MIN_SOURCES}+ from {SUPPORT_MIN_CONTENT_ITEMS}+"
    ))

    # Rule 2 - no rejection nearby: none of its source records is
    # touched by a link you rejected, or shared with a digest you
    # rejected.
    rejected_links = []
    rejected_digests = []

    if context_ids:
        marks = ",".join(["?"] * len(context_ids))

        cursor.execute(f"""
            SELECT id
            FROM context_links
            WHERE status = 'rejected'
            AND (
                source_context_id IN ({marks})
                OR target_context_id IN ({marks})
            )
        """, context_ids + context_ids)

        rejected_links = [row[0] for row in cursor.fetchall()]

        cursor.execute(f"""
            SELECT DISTINCT k.id
            FROM knowledge_items AS k
            JOIN knowledge_sources AS s
                ON s.knowledge_id = k.id
            WHERE k.status = 'rejected'
            AND k.id != ?
            AND s.context_id IN ({marks})
        """, [knowledge_id] + context_ids)

        rejected_digests = [row[0] for row in cursor.fetchall()]

    if rejected_links or rejected_digests:
        notes = []

        if rejected_links:
            notes.append(
                "rejected link(s) "
                + ", ".join(str(item) for item in rejected_links)
            )

        if rejected_digests:
            notes.append(
                "rejected knowledge "
                + ", ".join(str(item) for item in rejected_digests)
            )

        detail = "touched by " + "; ".join(notes)

    else:
        detail = "no rejected link or digest uses these sources"

    results.append((
        "no_rejection",
        not (rejected_links or rejected_digests),
        detail
    ))

    # Rule 3 - faithful: every sentence the digest quotes must still be
    # found word for word in one of its source records.
    quoted = [
        line[2:].strip()
        for line in digest_text.splitlines()
        if line.startswith("- ")
    ]

    source_texts = [source[2] or "" for source in sources]

    missing = [
        sentence for sentence in quoted
        if not any(sentence in text for text in source_texts)
    ]

    if not quoted:
        results.append((
            "faithful",
            False,
            "no quoted sentences found (older digest format; "
            "it cannot be verified)"
        ))

    else:
        results.append((
            "faithful",
            not missing,
            f"{len(quoted) - len(missing)} of {len(quoted)} quoted "
            "sentence(s) found word for word in the sources"
        ))

    passed = all(ok for _, ok, _ in results)

    return passed, results


# One line per rule, joined for storing in the database.
def format_check_notes(results):

    return " | ".join(
        f"{rule}: {'PASS' if ok else 'FAIL'} - {detail}"
        for rule, ok, detail in results
    )


# Shows the rule results on screen.
def print_check_results(results):

    for rule, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {rule}: {detail}")


# Runs the checks and records the outcome. Only provisional and
# supported items can change (provisional -> supported on a pass,
# supported -> provisional on a fail). Established and rejected items
# are YOUR decisions and are never touched. Returns a small dictionary
# describing what happened, or None if the item does not exist.
def apply_support_check(knowledge_id):

    evaluation = evaluate_knowledge(knowledge_id)

    if evaluation is None:
        return None

    passed, results = evaluation

    cursor.execute("""
        SELECT status
        FROM knowledge_items
        WHERE id = ?
    """, (knowledge_id,))

    status = cursor.fetchone()[0]

    outcome = {
        "status": status,
        "passed": passed,
        "results": results,
        "change": "none"
    }

    if status in ("established", "rejected"):
        return outcome

    new_status = "supported" if passed else "provisional"

    cursor.execute("""
        UPDATE knowledge_items
        SET status = ?, checked_at = ?, check_notes = ?
        WHERE id = ?
    """, (
        new_status,
        timestamp(),
        format_check_notes(results),
        knowledge_id
    ))

    db.commit()

    if status != "supported" and new_status == "supported":
        outcome["change"] = "promoted"

    elif status == "supported" and new_status == "provisional":
        outcome["change"] = "demoted"

    outcome["status"] = new_status

    return outcome


# Runs an existing command with its printing switched off and hands
# back (its return value, everything it would have printed). This is
# how :learn and :update reuse the existing commands unchanged.
def run_quietly(function, *arguments):

    buffer = io.StringIO()

    with contextlib.redirect_stdout(buffer):
        result = function(*arguments)

    return result, buffer.getvalue()


# ------------------------------------------
# 18F. :learn  (NEW IN 1.2)
# ------------------------------------------
# One command per topic instead of four: extract, associate the topic,
# build the digest, run the automatic checks. The digest and the check
# results are shown in full; the quiet steps are summarised.
def learn_topic(topic):

    topic = topic.strip()

    if not topic:
        print('Usage: :learn "topic or question"')
        return

    print("\n========== LEARN ==========")
    print("Topic:", topic)

    new_sections, _ = run_quietly(extract_context)
    print("\n1. Extract:", new_sections or 0, "new section record(s)")

    created, notes = run_quietly(associate_topic, topic)

    if created is None:
        print("2. Associate: nothing to do")

        for line in notes.strip().splitlines():
            if line.strip():
                print("  ", line.strip())

    else:
        print("2. Associate:", created, "new provisional link(s)")

    print("3. Digest:")

    knowledge_id = synthesize_knowledge(topic)

    if knowledge_id is None:
        print("\nNo digest was built, so there is nothing to check.")
        return

    print("\n4. Automatic checks for Knowledge", knowledge_id)

    outcome = apply_support_check(knowledge_id)
    print_check_results(outcome["results"])

    status = outcome["status"]

    print("\nRESULT")

    if status == "supported":
        print(f"Knowledge {knowledge_id} is SUPPORTED (system-checked).")
        print("It passed every rule. That does not prove it is true.")
        print(f"To vouch for it yourself: :confirm knowledge {knowledge_id}")

    elif status == "established":
        print(f"Knowledge {knowledge_id} is already ESTABLISHED.")
        print("It was left exactly as you set it.")

    elif status == "rejected":
        print(f"Knowledge {knowledge_id} was REJECTED earlier.")
        print("It was left exactly as you set it.")

    else:
        failed = [rule for rule, ok, _ in outcome["results"] if not ok]

        print(
            f"Knowledge {knowledge_id} stays PROVISIONAL. "
            f"Failed: {', '.join(failed)}."
        )
        print(f"If you trust it anyway: :confirm knowledge {knowledge_id}")

    print("===========================")


# ------------------------------------------
# 18G. :update  (NEW IN 1.2)
# ------------------------------------------
# The routine chores in one command: extract, classify and associate
# everything, then re-run the automatic checks on every provisional or
# supported digest. Established and rejected digests are not touched.
def update_brain():

    print("\n========== UPDATE ==========")

    new_sections, _ = run_quietly(extract_context)
    print("Extract:", new_sections or 0, "new section record(s)")

    run_quietly(classify_records)

    cursor.execute("SELECT COUNT(*) FROM context_items")
    print("Classify:", cursor.fetchone()[0], "context record(s)")

    created, _ = run_quietly(associate_all)
    print("Associate:", created or 0, "new provisional link(s)")

    cursor.execute("""
        SELECT id
        FROM knowledge_items
        WHERE status IN ('provisional', 'supported')
        ORDER BY id ASC
    """)

    pending = [row[0] for row in cursor.fetchall()]

    promoted = []
    demoted = []
    supported_now = 0
    provisional_now = 0

    for knowledge_id in pending:

        outcome = apply_support_check(knowledge_id)

        if outcome["change"] == "promoted":
            promoted.append(knowledge_id)

        elif outcome["change"] == "demoted":
            demoted.append(knowledge_id)

        if outcome["status"] == "supported":
            supported_now += 1

        else:
            provisional_now += 1

    print("\nRe-check of provisional and supported digests:")
    print("  Checked:", len(pending))

    if promoted:
        print(
            "  Promoted to supported:",
            ", ".join(str(item) for item in promoted)
        )

    if demoted:
        print(
            "  Demoted to provisional:",
            ", ".join(str(item) for item in demoted)
        )

    print("  Supported now:", supported_now)
    print("  Provisional now:", provisional_now)
    print("  Established and rejected items were not touched.")
    print("\nRun :knowledge to read the check results for each digest.")
    print("============================")


# ==========================================
# 19. RELATIONSHIP MAP
# ==========================================

def linkmap():

    cursor.execute("SELECT COUNT(*) FROM context_links")
    total_links = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM context_items")
    total_contexts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM knowledge_items")
    total_knowledge = cursor.fetchone()[0]

    print("\n========== BRAIN RELATIONSHIP MAP ==========")
    print("Context records:", total_contexts)
    print("Total relationships:", total_links)
    print("Knowledge records:", total_knowledge)

    cursor.execute("""
        SELECT status, COUNT(*)
        FROM context_links
        GROUP BY status
        ORDER BY status
    """)

    print("\nRELATIONSHIPS BY STATUS")

    for status, count in cursor.fetchall():
        print(f"{status}: {count}")

    cursor.execute("""
        SELECT relationship_type, COUNT(*)
        FROM context_links
        GROUP BY relationship_type
        ORDER BY COUNT(*) DESC
    """)

    print("\nRELATIONSHIPS BY TYPE")

    for relation, count in cursor.fetchall():
        print(f"{relation}: {count}")

    cursor.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT source_context_id AS node_id
            FROM context_links
            WHERE COALESCE(status, '') != 'rejected'

            UNION

            SELECT target_context_id AS node_id
            FROM context_links
            WHERE COALESCE(status, '') != 'rejected'
        )
    """)

    connected = cursor.fetchone()[0]
    isolated = max(0, total_contexts - connected)

    print("\nNETWORK STRUCTURE")
    print("Connected Context records:", connected)
    print("Isolated Context records:", isolated)

    cursor.execute("""
        SELECT node_id, COUNT(*) AS degree
        FROM (
            SELECT source_context_id AS node_id
            FROM context_links
            WHERE COALESCE(status, '') != 'rejected'

            UNION ALL

            SELECT target_context_id AS node_id
            FROM context_links
            WHERE COALESCE(status, '') != 'rejected'
        )
        GROUP BY node_id
        ORDER BY degree DESC
        LIMIT 10
    """)

    hubs = cursor.fetchall()

    print("\nMOST CONNECTED CONTEXT RECORDS")

    for context_id, degree in hubs:

        cursor.execute("""
            SELECT title
            FROM context_items
            WHERE id = ?
        """, (context_id,))

        result = cursor.fetchone()
        title = result[0] if result else "Unknown"

        print(
            f"Context {context_id}: "
            f"{title} ({degree} connections)"
        )

    cursor.execute("""
        SELECT id, title, content
        FROM context_items
    """)

    records = cursor.fetchall()

    concepts = {
        "CIPx": set(),
        "BRAIN": set(),
        "iQ": set()
    }

    for context_id, title, content in records:

        combined = (
            (title or "") + " " + (content or "")
        ).lower()

        for concept in concepts:

            pattern = (
                r"\b"
                + re.escape(concept.lower())
                + r"\b"
            )

            if re.search(pattern, combined):
                concepts[concept].add(context_id)

    print("\nFOUNDATIONAL CONCEPT RECORDS")

    for concept, ids in concepts.items():
        print(f"{concept}: {len(ids)} Context records")

    cursor.execute("""
        SELECT
            id,
            source_context_id,
            relationship_type,
            target_context_id,
            status
        FROM context_links
        WHERE COALESCE(status, '') != 'rejected'
        ORDER BY id
    """)

    edges = cursor.fetchall()

    pairs = [
        ("CIPx", "BRAIN"),
        ("CIPx", "iQ"),
        ("BRAIN", "iQ")
    ]

    print("\nDIRECT CONCEPT CONNECTIONS")

    for first, second in pairs:

        found = []

        for edge in edges:

            link_id, source, relation, target, status = edge

            connected_pair = (
                source in concepts[first]
                and target in concepts[second]
            ) or (
                source in concepts[second]
                and target in concepts[first]
            )

            if connected_pair:
                found.append(edge)

        print(f"\n{first} <-> {second}")

        if not found:
            print("No direct stored link found.")

        else:
            for edge in found[:5]:
                print(
                    f"Link {edge[0]}: "
                    f"{edge[1]} --{edge[2]}--> "
                    f"{edge[3]} [{edge[4]}]"
                )

            if len(found) > 5:
                print(f"{len(found) - 5} more direct links.")

    print("\n============================================")


# ==========================================
# 19A. RECOVERY (NEW IN 1.0)
# ==========================================
# Milestone 9 is only PARTLY complete: BRAIN can now make verified
# copies of what it knows, but there is no :restore or :import command
# yet. Restoring is a manual file copy (see the note :backup prints),
# and it should be rehearsed on a spare copy before you rely on it.

# The five tables that hold everything BRAIN has learned.
BRAIN_TABLES = [
    "content_items",
    "context_items",
    "context_links",
    "knowledge_items",
    "knowledge_sources"
]


# ------------------------------------------
# 19A-1. SMALL HELPERS
# ------------------------------------------

# Timestamp safe for file names (no colons or spaces).
def file_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# Row counts per table; used to prove a copy matches the original.
def table_counts(connection):
    return {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {quote(table)}"
        ).fetchone()[0]
        for table in BRAIN_TABLES
    }


# Everything after the command word, e.g. the folder in
# :backup "D:\My Backups". Taken from the raw text so Windows
# backslashes are not mangled by the command parser.
def command_argument(message):

    pieces = message.split(None, 1)

    if len(pieces) < 2:
        return ""

    return pieces[1].strip().strip('"').strip("'")


# Use the folder the person named, or the default one beside the
# script; create it if needed.
def resolve_folder(argument, default_folder):

    folder = argument if argument else default_folder
    folder = os.path.abspath(os.path.expanduser(folder))
    os.makedirs(folder, exist_ok=True)

    return folder


# A file path that does not overwrite anything already there.
def unique_path(folder, base_name, extension):

    path = os.path.join(folder, base_name + extension)
    counter = 2

    while os.path.exists(path):
        path = os.path.join(
            folder,
            f"{base_name}_{counter}{extension}"
        )
        counter += 1

    return path


# ------------------------------------------
# 19A-2. :backup  (step 3)
# ------------------------------------------

# Re-opens a backup file independently and checks that SQLite finds it
# healthy and that every table holds as many rows as the live database.
# A backup that fails this is deleted rather than left to be trusted.
def verify_database_file(path, expected_counts):

    try:
        copy = sqlite3.connect(path)

        try:
            rows = copy.execute("PRAGMA integrity_check").fetchall()

            if [row[0] for row in rows] != ["ok"]:
                return False, "integrity check failed"

            found = table_counts(copy)

        finally:
            copy.close()

    except sqlite3.Error as error:
        return False, str(error)

    if found != expected_counts:
        return False, "row counts differ from the live database"

    return True, "integrity check ok; row counts match"


# Makes a consistent copy of the whole database using SQLite's own
# backup routine (safe even though the database is open), then
# verifies the copy. Optional argument: a folder, e.g. a USB drive.
def backup_database(argument=""):

    try:
        folder = resolve_folder(argument, BACKUP_DIR)

    except OSError as error:
        print("Backup folder could not be used:", error)
        return

    db.commit()

    expected = table_counts(db)

    destination = unique_path(
        folder,
        "brain_iq_backup_" + file_stamp(),
        ".db"
    )

    try:
        copy = sqlite3.connect(destination)

        try:
            db.backup(copy)

        finally:
            copy.close()

    except (sqlite3.Error, OSError) as error:
        print("Backup failed:", error)

        if os.path.exists(destination):
            os.remove(destination)

        return

    verified, detail = verify_database_file(destination, expected)

    if not verified:
        os.remove(destination)
        print("Backup FAILED verification and was deleted:", detail)
        return

    print("\n========== BACKUP COMPLETE ==========")
    print("File:", destination)
    print("Size:", round(os.path.getsize(destination) / 1024, 1), "KB")
    print("Verification:", detail)

    for table, count in expected.items():
        print(f"  {table}: {count}")

    print("\nTo restore: close BRAIN, then copy this file over")
    print("brain_iq.db (beside brain_iq.py), keeping that name.")
    print("Rehearse this on a spare copy before relying on it.")
    print("=====================================")


# ------------------------------------------
# 19A-3. :export  (step 4)
# ------------------------------------------

# Writes every table to one human-readable JSON file that any program
# can read, with row counts and a SHA-256 checksum of the data. The
# file is written under a temporary name, read back and checked, and
# only then given its final name. Optional argument: a folder.
# NOTE: there is no :import yet, so an export is for portability and
# inspection; :backup is the way to protect against loss.
def export_data(argument=""):

    try:
        folder = resolve_folder(argument, EXPORT_DIR)

    except OSError as error:
        print("Export folder could not be used:", error)
        return

    db.commit()

    tables = {}

    for table in BRAIN_TABLES:

        result = db.execute(
            f"SELECT * FROM {quote(table)} ORDER BY 1"
        )

        names = [column[0] for column in result.description]

        tables[table] = [
            dict(zip(names, row))
            for row in result.fetchall()
        ]

    counts = {table: len(rows) for table, rows in tables.items()}

    try:
        checksum = hashlib.sha256(
            json.dumps(
                tables, sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()

    except TypeError as error:
        print("Export failed: a value cannot be written as JSON:", error)
        return

    package = {
        "format": "cipx-brain-iq-export",
        "format_version": 1,
        "program_version": "1.0",
        "exported_at": timestamp(),
        "row_counts": counts,
        "tables_sha256": checksum,
        "tables": tables
    }

    destination = unique_path(
        folder,
        "brain_iq_export_" + file_stamp(),
        ".json"
    )

    temporary = destination + ".tmp"

    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(package, handle, ensure_ascii=False, indent=2)

        with open(temporary, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)

        reloaded_checksum = hashlib.sha256(
            json.dumps(
                loaded["tables"], sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()

        reloaded_counts = {
            table: len(rows)
            for table, rows in loaded["tables"].items()
        }

        if reloaded_checksum != checksum or reloaded_counts != counts:
            raise ValueError("file did not read back identically")

        os.replace(temporary, destination)

    except (OSError, ValueError) as error:
        print("Export FAILED verification:", error)

        if os.path.exists(temporary):
            os.remove(temporary)

        return

    print("\n========== EXPORT COMPLETE ==========")
    print("File:", destination)
    print("Size:", round(os.path.getsize(destination) / 1024, 1), "KB")
    print("Verification: read back; checksum and row counts match")
    print("Checksum:", checksum[:16] + "...")

    for table, count in counts.items():
        print(f"  {table}: {count}")

    print("=====================================")


# ==========================================
# 20. HELP
# ==========================================

# UPDATED IN 1.0: the help text below gained a RECOVERY section that
# lists :backup and :export. Nothing else in the help changed.
def show_help():

    print("""
========== CIPx | BRAIN iQ ==========

Anything you type that does not start with ":" is saved
as content exactly as written.

CONTENT

:paste
    Save several lines as ONE content item.
    End with a line containing only :end

:memory
    View original acquired content.

:extract
    Split content into sections in the Context Body.

CONTEXT

:classify
    Classify Context Body records.

:context
    View Context Body records.

ASSOCIATION

:associate CIPx
    Discover relationships around a topic.

:associate BRAIN
    Discover BRAIN-related relationships.

:associate iQ
    Discover iQ-related relationships.

:associate all
    Search all Context records for relationships.

RELATIONSHIPS

:link 1 supports 2
    Manually link Context 1 to Context 2.

:links
    View all stored relationships.

:confirm 1
    Mark relationship 1 as established.

:reject 1
    Mark relationship 1 as rejected.

KNOWLEDGE ACQUISITION

:digest "topic or question"
    Build and store a bounded, source-grouped evidence digest
    from relevant Context records (alias: :synthesize).

:learn "topic"
    One step: extract, associate the topic, build a digest and
    run the automatic checks. A digest that passes becomes
    "supported" (system-checked). Only you can make it
    "established".

:update
    Extract, classify and associate everything, then re-check
    every provisional or supported digest.

:knowledge
    View stored Knowledge Body records and their sources.

:confirm knowledge 1
    Mark Knowledge item 1 as established.

:reject knowledge 1
    Mark Knowledge item 1 as rejected. It stays stored but is
    hidden from :retrieve. (:confirm knowledge 1 restores it.)

KNOWLEDGE RETRIEVAL

:retrieve
    Enter a keyword, phrase or question.

:retrieve KEYWORD
    Search Context Body and Knowledge Body.

:retrieve "question or phrase"
    Search stored knowledge and related Context records.

:linkmap
    Display the relationship network summary.

RECOVERY

:backup
    Make a verified copy of the whole database in the
    backups folder beside this script.

:backup "D:\\folder"
    Same, but into a folder you choose (for example a USB drive).

:export
    Write all data to a portable, checksummed JSON file in the
    exports folder. (There is no :import yet.)

OTHER

:help
    Display available commands.

:exit
    Close the program.

=====================================
""")


# ==========================================
# 21. COMMAND INTERFACE
# ==========================================

print("\n====================================")
print("          CIPx | BRAIN iQ")
# UPDATED IN 1.0: banner shows the new version, then the database
# location and the results of the startup checks (step 1 and step 2).
print("  Version 1.2")
print("  Local Knowledge Acquisition, Digests, Recovery & Review")
print("====================================")

print("\nDatabase:", DATABASE)

for note in startup_notes:
    print(note)

show_help()

try:

    while True:

        try:
            message = input("\nYou: ").strip()

        except EOFError:
            print("\nSession ended.")
            break

        if not message:
            continue

        # Fix 1: only ":" lines are commands. Everything else is
        # content and is never run through the command parser.
        if not message.startswith(":"):
            acquire_content(message)
            continue

        try:
            parts = shlex.split(message)

        except ValueError:
            # Unbalanced quote or apostrophe in a command argument.
            parts = message.split()

        command = parts[0].lower()

        if command == ":exit":
            print("\nSession ended.")
            break

        elif command == ":help":
            show_help()

        # NEW IN 1.0: recovery commands (steps 3 and 4). Each takes an
        # optional folder, read from the raw text so Windows paths with
        # backslashes or spaces survive.
        elif command == ":backup":
            backup_database(command_argument(message))

        elif command == ":export":
            export_data(command_argument(message))

        elif command == ":paste":
            paste_content()

        elif command == ":memory":
            retrieve_content()

        elif command == ":extract":
            extract_context()

        elif command == ":classify":
            classify_records()

        elif command == ":context":
            retrieve_context()

        elif command == ":links":
            retrieve_links()

        elif command == ":linkmap":
            linkmap()

        # NEW IN 1.2: one-step learning and bulk maintenance.
        elif command == ":learn":

            if len(parts) > 1:
                learn_topic(" ".join(parts[1:]))

            else:
                print('Usage: :learn "topic or question"')

        elif command == ":update":
            update_brain()

        elif command == ":knowledge":
            retrieve_knowledge_body()

        elif command in (":synthesize", ":digest"):

            if len(parts) > 1:
                topic = " ".join(parts[1:])
                synthesize_knowledge(topic)

            else:
                synthesize_knowledge()

        elif command == ":retrieve":

            if len(parts) > 1:
                query = " ".join(parts[1:])
                retrieve_knowledge(query)

            else:
                retrieve_knowledge()

        elif command == ":link":

            if len(parts) == 4:
                create_link(
                    parts[1],
                    parts[2],
                    parts[3]
                )

            else:
                print("Usage: :link SOURCE_ID relation TARGET_ID")

        elif command == ":associate":

            if len(parts) < 2:
                print('Usage: :associate "TOPIC" or :associate all')

            elif len(parts) == 2 and parts[1].lower() == "all":
                associate_all()

            else:
                topic = " ".join(parts[1:])
                associate_topic(topic)

        elif command == ":confirm":

            # NEW IN 1.1: ":confirm knowledge 3" reviews a Knowledge
            # Body item. ":confirm 1" still confirms LINK 1 as before.
            if len(parts) == 3 and parts[1].lower() in ("knowledge", "k"):
                review_knowledge(parts[2], "established")

            elif len(parts) == 2:
                update_link_status(
                    parts[1],
                    "established"
                )

            else:
                print("Usage: :confirm LINK_ID")
                print("       :confirm knowledge KNOWLEDGE_ID")

        elif command == ":reject":

            # NEW IN 1.1: ":reject knowledge 3" reviews a Knowledge
            # Body item. ":reject 1" still rejects LINK 1 as before.
            if len(parts) == 3 and parts[1].lower() in ("knowledge", "k"):
                review_knowledge(parts[2], "rejected")

            elif len(parts) == 2:
                update_link_status(
                    parts[1],
                    "rejected"
                )

            else:
                print("Usage: :reject LINK_ID")
                print("       :reject knowledge KNOWLEDGE_ID")

        else:
            print("Unknown command. Type :help.")

finally:

    db.close()
    print("\nDatabase connection closed.")
