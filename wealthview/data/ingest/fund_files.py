"""Fund values from the reports the person keeps in a folder (v1.23): CSV exports and PDF reports, read on this computer only.

Three readers, tried in this order for every file:
  1. csv_extract  - a table with a date column and a value column (NAV, Wert, Kurs, Marktwert, value ...): the newest row.
  2. rule_extract - a PDF whose text has a labelled single number ("Net asset value", "Kapitalkonto", "Fair Value as of 30 Jun, 2025" ...).
  3. llm_extract  - any other layout: the local LM Studio model is asked to read the relevant lines and answer with JSON. Its answer is only
                    accepted when the number really stands in the text (so it cannot make one up) and passes the sanity check.
Nothing leaves the computer: the text goes to the LM Studio server on this machine (the `ask` function the caller passes in), never to the web.
Standard library only; PDF text comes from pdftotext or pypdf when they are installed, else from a small built-in reader."""
from __future__ import annotations
import csv
import datetime as dt
import io
import json
import re
import shutil
import subprocess
import zlib
from pathlib import Path
from typing import Any, Callable


MAX_FILES = 60
MAX_TEXT = 6500                 # characters sent to the model
SANITY_X = 20.0                 # a value more than 20 times what was paid in is probably the whole fund, not the person's share
_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_MONTHS.update({"mär": 3, "mai": 5, "okt": 10, "dez": 12})

# ---------------------------------------------------------------- PDF text
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TEXT_OP = re.compile(rb"\[(.*?)\]\s*TJ|\((.*?)(?<!\\)\)\s*Tj|<([0-9A-Fa-f\s]+)>\s*Tj", re.S)


def _unescape(b: bytes) -> str:
    b = re.sub(rb"\\([nrtbf()\\])", lambda m: {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"", b"f": b""}.get(m.group(1), m.group(1)), b)
    b = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 255]), b)
    return b.decode("cp1252", "replace")


def builtin_pdf_text(data: bytes) -> str:
    """Text of the simple text objects of a PDF (compressed or not). Fonts with their own encoding give no readable text - then it is empty-ish."""
    out: list[str] = []
    for m in _STREAM.finditer(data):
        body = m.group(1)
        try:
            body = zlib.decompress(body)
        except zlib.error:
            pass
        if b"BT" not in body:
            continue
        for t in _TEXT_OP.finditer(body):
            if t.group(1) is not None:
                out.append("".join(_unescape(s) for s in re.findall(rb"\(((?:\\.|[^\\)])*)\)", t.group(1))))
            elif t.group(2) is not None:
                out.append(_unescape(t.group(2)))
            else:
                hexs = re.sub(rb"\s", b"", t.group(3))
                out.append(bytes.fromhex(hexs.decode() + ("0" if len(hexs) % 2 else "")).decode("latin-1"))
        out.append("\n")
    return re.sub(r"[ \t]+", " ", "\n".join(out))


def pdf_text(path: Path, which: Callable[[str], str | None] = shutil.which, run: Callable[..., Any] = subprocess.run) -> str:
    """The text of a PDF: pdftotext if installed, else pypdf if installed, else the built-in reader."""
    exe = which("pdftotext")
    if exe:
        try:
            r = run([exe, "-layout", str(path), "-"], capture_output=True, timeout=120, check=False)
            if r.returncode == 0 and r.stdout.strip():
                return str(r.stdout.decode("utf-8", "replace"))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import pypdf  # type: ignore[import-not-found,unused-ignore]
        return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
    except Exception:                       # noqa: BLE001 - any parser trouble means: use the built-in reader
        pass
    return builtin_pdf_text(path.read_bytes())


# ---------------------------------------------------------------- dates and numbers
def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def find_date(text: str) -> str | None:
    """The reporting date in a text: '30 Jun, 2025', '30.06.2025', '2025-06-30' or 'Q2 2025' (the end of the quarter). Newest one that is found first by the labelled forms."""
    for pat in (r"(?:as of|per|zum|stand|as at|reporting date)[:\s]+(\d{1,2})\.?\s*([A-Za-zäÄ]{3})[a-z]*\.?,?\s+(\d{4})", r"(?:as of|per|zum|stand|as at)[:\s]+(\d{1,2})\.(\d{1,2})\.(\d{4})"):
        m = re.search(pat, text, re.I)
        if m:
            mon = _MONTHS.get(m.group(2).lower()[:3]) if not m.group(2).isdigit() else int(m.group(2))
            if mon:
                return _iso(int(m.group(3)), mon, int(m.group(1)))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    ds = [_iso(int(y), int(mo), int(d)) for d, mo, y in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)]
    ds = [d for d in ds if d]
    if ds:
        return max(ds)
    m = re.search(r"\bQ([1-4])[ _/-]*(20\d\d)\b|\b(20\d\d)[ _/-]*Q([1-4])\b", text)
    if m:
        q, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        mo = int(q) * 3
        return _iso(int(y), mo, 31 if mo in (3, 12) else 30)
    return None


_NUMBER = re.compile(r"(?<![\w.,])\(?-?\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d+)?\)?(?![\w])|(?<![\w.,])-?\d+(?:[.,]\d+)?(?![\w])")


def to_number(t: str) -> float | None:
    """A printed amount in German or English style ('1.234,56', '152,576,255', '1 234.5', '(8,037,563)' = minus) as a float."""
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-")
    t = re.sub(r"[^\d.,]", "", t)
    if not t:
        return None
    last = max(t.rfind("."), t.rfind(","))
    if last >= 0:
        mark, head, tail = t[last], t[:last], t[last + 1:]
        other = "," if mark == "." else "."
        if other in head or (head.count(mark) == 0 and len(tail) != 3) or (head.count(mark) == 0 and head in ("", "0")):
            t = head.replace(".", "").replace(",", "") + "." + tail            # the last mark is the decimal point
        else:
            t = t.replace(".", "").replace(",", "")                              # marks only group thousands
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _numbers(s: str) -> list[float]:
    vals = []
    for m in _NUMBER.finditer(s):
        v = to_number(m.group(0).strip().replace(" ", ""))
        if v is not None:
            vals.append(v)
    return vals


# ---------------------------------------------------------------- reader 1: CSV
_DATE_H = ("date", "datum", "stichtag", "as of", "day", "period", "stand", "bewertungstag")
_VAL_H = ("nav", "net asset", "wert", "value", "kurs", "price", "preis", "marktwert", "fair value", "kapitalkonto", "close", "schluss", "rücknahme")


def _cell_date(s: str) -> str | None:
    s = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", s)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        return _iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def csv_extract(text: str) -> dict[str, Any] | None:
    """{date, value, series:[(date, value)], how:'csv'} from a table with a date column and a value column; None when it is not one."""
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=";,\t|")
        rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    except csv.Error:
        return None
    for hi, head in enumerate(rows[:12]):
        low = [c.strip().lower() for c in head]
        dc = next((i for i, c in enumerate(low) if any(k in c for k in _DATE_H)), None)
        vc = next((i for i, c in enumerate(low) if i != dc and any(k in c for k in _VAL_H)), None)
        if dc is None or vc is None:
            continue
        pts: dict[str, float] = {}
        for r in rows[hi + 1:]:
            if len(r) <= max(dc, vc):
                continue
            d, v = _cell_date(r[dc]), to_number(r[vc].strip())
            if d and v is not None and v >= 0:
                pts[d] = v
        if pts:
            series = sorted(pts.items())
            return {"date": series[-1][0], "value": series[-1][1], "series": series, "how": "csv"}
    return None


# ---------------------------------------------------------------- reader 2: labelled lines
_LABELS = re.compile(r"(capital account at fair value|net asset value|\bNAV\b|kapitalkonto|beteiligungswert|wert der beteiligung|marktwert|fair value of (?:your|the) (?:interest|investment)|current value|aktueller wert|depotwert|your share|ihr anteil)", re.I)
_PAID = re.compile(r"(paid[- ]in capital|eingezahltes kapital|capital called|eingezahlt)", re.I)


def _one_number_lines(text: str, labels: re.Pattern[str]) -> list[tuple[str, float]]:
    out = []
    for line in text.splitlines():
        line_s = line.strip()
        m = labels.search(line_s)
        if not m or m.start() > 8 or "(x)" in line_s or "%" in line_s:       # the label starts the line; ratios and percentages are no amounts
            continue
        line = line_s
        rest = line[m.end():]
        rest = re.sub(r"\b\d{1,2}\.?\s*[A-Za-zä]{3}[a-z]*\.?,?\s+\d{4}\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b|\bQ[1-4]\s*20\d\d\b", " ", rest)   # dates are not amounts
        vals = _numbers(rest)
        if len(vals) == 1 and vals[0] >= 100:
            out.append((line.strip(), vals[0]))
    return out


def rule_extract(text: str, name: str = "") -> dict[str, Any] | None:
    """{date, value, paid_in, how:'rules'} when exactly one labelled value stands alone on its line (several numbers on a line = fund total next to
    the investor, which needs the model); None otherwise."""
    hits = _one_number_lines(text, _LABELS)
    vals = {v for _, v in hits}
    if len(vals) != 1:
        return None
    paid = {v for _, v in _one_number_lines(text, _PAID)}
    d = find_date(hits[0][0]) or find_date(text) or find_date(name)
    return {"date": d, "value": vals.pop(), "paid_in": paid.pop() if len(paid) == 1 else None, "how": "rules"}


# ---------------------------------------------------------------- reader 3: the local model
PROMPT = ("You read a fund report. Find what the INVESTOR (not the whole fund) holds: the value of the investor's capital account / units / share at the "
          "reporting date. Answer with ONE line of JSON and nothing else: "
          '{"date":"YYYY-MM-DD","value":number,"paid_in":number or null,"currency":"EUR"}. '
          "Use the numbers exactly as printed in the text (no rounding, no calculating). If the text has no such value answer {\"value\":null}.")
_KEYWORDS = re.compile(r"capital account|net asset|\bnav\b|fair value|paid[- ]in|kapitalkonto|beteiligung|marktwert|anteil|investor|reporting date|as of|stand|zum", re.I)


def relevant_text(text: str, limit: int = MAX_TEXT) -> str:
    """The lines around the keywords (a few before and after), cut to `limit` characters, so a long report fits into the model."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    keep: set[int] = set()
    for i, ln in enumerate(lines):
        if _KEYWORDS.search(ln):
            keep.update(range(max(0, i - 1), min(len(lines), i + 3)))
    out = "\n".join(re.sub(r"\s{3,}", "   ", lines[i]) for i in sorted(keep) if lines[i].strip())
    return out[:limit]


def _digits(v: float) -> list[str]:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    ip, _, fp = s.partition(".")
    return [ip + fp, f"{int(ip):,}".replace(",", ".") + ("," + fp if fp else ""), f"{int(ip):,}" + ("." + fp if fp else "")]


def standing_in(text: str, v: float) -> bool:
    """True when the number is really printed in the text (in German or English style) - the check against a made-up answer."""
    flat = re.sub(r"[\s]", "", text)
    return any(d in flat for d in _digits(v))


def parse_reply(reply: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*?\}", reply or "", re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except ValueError:
        return None
    return j if isinstance(j, dict) else None


def llm_extract(text: str, ask: Callable[[str, str], str], name: str = "") -> dict[str, Any] | None:
    """Ask the local model (ask(system, user) -> reply) for the investor's value; checked against the text. None when it cannot say."""
    ctx = relevant_text(text)
    if not ctx.strip():
        return None
    j = parse_reply(ask(PROMPT, ctx))
    if not j or not isinstance(j.get("value"), (int, float)) or isinstance(j.get("value"), bool) or j["value"] <= 0:
        return None
    v = float(j["value"])
    if not standing_in(text, v):
        return None
    paid = j.get("paid_in")
    paid = float(paid) if isinstance(paid, (int, float)) and not isinstance(paid, bool) and paid > 0 and standing_in(text, float(paid)) else None
    d = j.get("date") if isinstance(j.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", j["date"]) else None
    return {"date": d or find_date(ctx) or find_date(name), "value": v, "paid_in": paid, "how": "model"}


# ---------------------------------------------------------------- the folder
def sane(value: float, invested: float | None) -> bool:
    """False when the value is far above what was paid in (probably the whole fund's number, not the person's share)."""
    return not invested or invested <= 0 or value <= invested * SANITY_X


def read_file(path: Path, ask: Callable[[str, str], str] | None, invested: float | None = None) -> dict[str, Any] | None:
    """{date, value, how, paid_in?, series?} of one CSV or PDF file, or {'note': why not} / None."""
    ext = path.suffix.lower()
    try:
        if ext in (".csv", ".txt"):
            r = csv_extract(path.read_text(encoding="utf-8-sig", errors="replace"))
            text = ""
        elif ext == ".pdf":
            text = pdf_text(path)
            r = rule_extract(text, path.name)
            if r is None and ask is not None and len(text.strip()) > 80:
                try:
                    r = llm_extract(text, ask, path.name)
                except (RuntimeError, OSError, KeyError, TypeError, ValueError):
                    return {"note": "this report needs LM Studio to be read - start it and load a model"}
            if r is None and ask is None and text.strip():
                return {"note": "this report needs LM Studio to be read - start it and load a model"}
        else:
            return None
    except (OSError, ValueError, UnicodeError) as e:
        return {"note": f"could not read {path.name}: {e}"}
    if r is None:
        return None
    if r.get("date") is None:
        r["date"] = dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    if not sane(float(r["value"]), invested):
        return {"note": f"{path.name}: the number found looks like the whole fund, not your share - type your value or point to your own statement"}
    return r


def read_folder(folder: str, ask: Callable[[str, str], str] | None = None, invested: float | None = None,
                cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """The newest value found in the files of a folder: {value, date, paid_in, file, how, series, files, note}. Never raises; 'note' says what went wrong.
    cache (a dict the caller keeps between runs) remembers the answer per file and change time, so the model is asked once per file."""
    d = Path(folder)
    if not folder or not d.is_dir():
        return {"files": 0, "note": "the folder does not exist"}
    files = sorted((p for p in d.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".pdf", ".txt")), key=lambda p: p.name)[:MAX_FILES]
    found: list[dict[str, Any]] = []
    notes: list[str] = []
    for p in files:
        st = p.stat()
        key = f"{p.name}|{st.st_size}|{int(st.st_mtime)}|{int(invested or 0)}"
        if cache is not None and key in cache:
            r = cache[key]
        else:
            r = read_file(p, ask, invested)
            if cache is not None and (r is None or "note" not in r or "LM Studio" not in r["note"]):
                cache[key] = r
        if r and "value" in r:
            found.append({**r, "file": p.name})
        elif r and r.get("note"):
            notes.append(r["note"])
    if not found:
        return {"files": len(files), "note": notes[0] if notes else ("no readable value in " + (f"{len(files)} files" if files else "this folder"))}
    best = max(found, key=lambda r: (r["date"], r.get("how") == "csv"))
    series = sorted({(r["date"], r["value"]) for r in found if "series" not in r} | {tuple(x) for r in found for x in r.get("series", [])})
    return {**best, "series": [list(x) for x in series], "files": len(files), "note": None}
