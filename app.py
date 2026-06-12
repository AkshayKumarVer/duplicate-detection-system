"""
Duplicate Detection System — Previous-Exam Report Analyzer
==========================================================
Streamlit app that loads a TrustView HTML match/mismatch report from a URL,
parses every current-vs-previous candidate match, and flags records whose
CURRENT father name differs from the PREVIOUS father name (impersonation).

Deploy on Streamlit Community Cloud:
  1. Push app.py + requirements.txt to a GitHub repo.
  2. Go to https://share.streamlit.io  ->  New app  ->  pick the repo  ->  app.py.
Run locally:
  pip install -r requirements.txt
  streamlit run app.py
"""

import re
import difflib

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DEFAULT_URL = "https://trustview.in/dwnld/upprpb25_10%20Jun'26%20S1_repscoreprvgrp1.html"
DEFAULT_DEDUP_URL = "https://trustview.in/dwnld/upprpb2510Jun%2726S1_dedup_.html"

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PREV_INFO_RE = re.compile(r"^\S+-\d+-.+?-(True|False)-", re.I)
CUR_INFO_RE = re.compile(r"^\d{6,}-.+?-(True|False)-", re.I)

st.set_page_config(page_title="Duplicate Detection System", page_icon="🔍",
                   layout="wide")

# --------------------------------------------------------------------------- #
# Theme / CSS
# --------------------------------------------------------------------------- #
METRIC_COLORS = {
    "TOTAL": "#6366f1", "IMPERSONATION": "#ef4444", "SAME DETAILS": "#3b82f6",
    "SIBLING/TWIN": "#14b8a6", "INVALID": "#f59e0b",
}


def _metric_color(label):
    for key, color in METRIC_COLORS.items():
        if key in label:
            return color
    return "#6366f1"


def inject_css():
    st.markdown(
        """
        <style>
        .stApp { background: #f4f6fb; }
        .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px; }

        /* Header banner */
        .app-header {
            background: linear-gradient(120deg, #4f46e5 0%, #7c3aed 50%, #2563eb 100%);
            border-radius: 18px; padding: 1.4rem 1.8rem; margin-bottom: 1.2rem;
            box-shadow: 0 10px 30px rgba(79,70,229,.25); color: #fff;
        }
        .app-header h1 { color:#fff; font-size: 1.7rem; font-weight: 800;
            margin: 0; letter-spacing:.5px; }
        .app-header p { color: #e0e7ff; margin:.35rem 0 0; font-size:.95rem; }

        /* Metric cards */
        .metric-row { display:flex; gap:14px; flex-wrap:wrap; margin:.4rem 0 1.1rem; }
        .metric-card { flex:1; min-width:150px; background:#fff; border-radius:14px;
            padding:1rem 1.2rem; border-top:4px solid #6366f1;
            box-shadow:0 4px 14px rgba(17,24,39,.06); transition:transform .15s ease; }
        .metric-card:hover { transform: translateY(-3px); }
        .metric-label { font-size:.72rem; font-weight:700; letter-spacing:.8px;
            text-transform:uppercase; color:#6b7280; }
        .metric-value { font-size:2rem; font-weight:800; line-height:1.1; margin-top:.2rem; }

        /* NEW / OLD badge */
        .status-badge { display:inline-flex; gap:14px; align-items:center;
            background:#fff; border:1px solid #e5e7eb; border-radius:999px;
            padding:.35rem 1rem; font-size:.85rem; font-weight:600; margin-bottom:.3rem;
            box-shadow:0 2px 8px rgba(17,24,39,.05); }
        .pill-new { color:#16a34a; } .pill-old { color:#6b7280; }

        /* URL container card */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius:14px; box-shadow:0 4px 14px rgba(17,24,39,.05); }

        /* Buttons */
        .stButton > button { border-radius:10px; font-weight:600; }
        .stDownloadButton > button { border-radius:10px; font-weight:600; }

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] { gap:8px; }
        .stTabs [data-baseweb="tab"] {
            background:#fff; border-radius:10px 10px 0 0; padding:10px 20px;
            font-weight:700; border:1px solid #e5e7eb; border-bottom:none; }
        .stTabs [aria-selected="true"] {
            background: linear-gradient(120deg,#4f46e5,#7c3aed); color:#fff !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _to_float(x):
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def _parse_current_cell(cell):
    divs = [t for t in (d.get_text(" ", strip=True) for d in cell.find_all("div")) if t]
    info = father = dob = None
    for t in divs:
        if info is None and CUR_INFO_RE.match(t):
            info = t
        if t.startswith("Father"):
            m = re.match(r"Father\s*:\s*(.*?)\s*\|\|\s*DOB:\s*(\d{4}-\d{2}-\d{2})", t)
            if m:
                father, dob = m.group(1).strip(), m.group(2)
    parts = info.split("-") if info else []
    name = parts[1].strip() if len(parts) >= 2 else None
    cid = parts[0].strip() if parts else None
    return {"id": cid, "name": name, "father": father, "dob": dob}


def _parse_prev_cell(cell):
    divs = [t for t in (d.get_text(" ", strip=True) for d in cell.find_all("div")) if t]
    matches, i = [], 0
    while i < len(divs):
        t = divs[i]
        if PREV_INFO_RE.match(t):
            info = t
            fdob = ""
            if i + 1 < len(divs) and not PREV_INFO_RE.match(divs[i + 1]):
                fdob, i = divs[i + 1], i + 2
            else:
                i += 1
            parts = info.split("-")
            pid = parts[1].strip() if len(parts) > 1 else None
            name = parts[2].strip() if len(parts) > 2 else None
            face = _to_float(parts[6]) if len(parts) > 6 else None
            cross = _to_float(parts[7]) if len(parts) > 7 else None
            father = dob = None
            if fdob:
                dm = DATE_RE.search(fdob)
                if dm:
                    dob, father = dm.group(1), fdob[: dm.start()].strip()
                else:
                    father = fdob.strip()
            exam = parts[0].strip() if parts else None
            matches.append({"id": pid, "name": name, "father": father, "dob": dob,
                            "face": face, "cross": cross, "exam": exam})
        else:
            i += 1
    return matches


def _parse_bio_cell(cell):
    out = []
    for chunk in cell.get_text(" ", strip=True).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "|" in chunk:
            score, _, verdict = chunk.partition("|")
            out.append((_to_float(score), verdict.strip()))
        elif chunk.upper() == "NA":
            out.append((None, "NA"))
        else:
            out.append((_to_float(chunk), ""))
    return out


def parse_report(html):
    """Return a list of flat dict rows (one per current-vs-previous match)."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue
        sn = tds[0].get_text(strip=True)
        cur = _parse_current_cell(tds[2])
        prev_matches = _parse_prev_cell(tds[3])
        bios = _parse_bio_cell(tds[4])
        time = tds[5].get_text(strip=True)
        for idx, pm in enumerate(prev_matches):
            bio_score, bio_verdict = bios[idx] if idx < len(bios) else (None, "")
            rows.append({
                "SN": sn,
                "Current ID": cur["id"], "Prev ID": f"{pm['exam']}-{pm['id']}",
                "Current Name": cur["name"], "Current Father": cur["father"],
                "Current DOB": cur["dob"],
                "Prev Name": pm["name"], "Prev Father": pm["father"],
                "Prev DOB": pm["dob"], "Prev Exam": pm["exam"],
                "Face Score": pm["face"], "Cross Score": pm["cross"],
                "Bio Score": bio_score, "Bio Verdict": bio_verdict,
                "time": time,
            })
    return rows


_IMG_RE = re.compile(r'data:image/[^;"\']+;base64,[^"\']+')


@st.cache_data(show_spinner=False, ttl=600)
def fetch_html(url):
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    # Strip embedded base64 images — we never display them, and dropping them
    # turns an 80+ MB report into a few hundred KB (vital for free-tier memory).
    return _IMG_RE.sub("", resp.text)


# --------------------------------------------------------------------------- #
# Parsing — DEDUP report (pairwise enroll-to-enroll matches)
# Each row holds two candidate boxes (A = current sitting, B = other sitting),
# each described by a <p>:
#   enrollNo, NAME, FATHER, DOB, exam-date-shift, center, score
# plus columns: enroll-to-enroll score, app-to-app score, bio score+verdict.
# --------------------------------------------------------------------------- #
def _parse_dedup_person(text):
    parts = [p.strip() for p in text.split(",")]
    enroll = parts[0] if parts else None
    dob_idx = next((i for i, p in enumerate(parts) if DATE_RE.fullmatch(p)), None)
    if dob_idx is None or dob_idx < 2:
        # fall back to fixed positions
        return {"enroll": enroll,
                "name": parts[1] if len(parts) > 1 else None,
                "father": parts[2] if len(parts) > 2 else None,
                "dob": parts[3] if len(parts) > 3 else None,
                "shift": parts[4] if len(parts) > 4 else None}
    name = ", ".join(parts[1:dob_idx - 1]).strip()
    father = parts[dob_idx - 1]
    dob = parts[dob_idx]
    shift = parts[dob_idx + 1] if len(parts) > dob_idx + 1 else None
    return {"enroll": enroll, "name": name, "father": father,
            "dob": dob, "shift": shift}


def _parse_dedup_bio(text):
    text = text.strip().rstrip(",").strip()
    if not text:
        return None, ""
    m = re.match(r"^([\d.]+)\s*(.*)$", text)
    if m:
        return _to_float(m.group(1)), m.group(2).strip()
    if text.upper().startswith("NA"):
        return None, "NA"
    return None, text[:24]


def parse_dedup_report(html):
    """Return a list of flat dict rows (one per matched enroll pair)."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
        ps = [p.get_text(" ", strip=True) for p in tds[1].find_all("p")]
        if len(ps) < 2:
            continue
        a, b = _parse_dedup_person(ps[0]), _parse_dedup_person(ps[1])
        bio_score, bio_verdict = _parse_dedup_bio(tds[4].get_text(" ", strip=True))
        rows.append({
            "SN": tds[0].get_text(strip=True),
            "Current Enroll": a["enroll"], "Current Name": a["name"],
            "Current Father": a["father"], "Current DOB": a["dob"],
            "Current Shift": a["shift"],
            "Prev Enroll": b["enroll"], "Prev Name": b["name"],
            "Prev Father": b["father"], "Prev DOB": b["dob"],
            "Prev Shift": b["shift"],
            "Enroll Score": _to_float(tds[2].get_text(strip=True)),
            "App Score": _to_float(tds[3].get_text(strip=True)),
            "Bio Score": bio_score, "Bio Verdict": bio_verdict,
        })
    return rows


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def _norm(s):
    if not isinstance(s, str):
        return ""
    return re.sub(r"[^a-z]", "", s.lower())


def father_similarity(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def classify(df, father_th):
    df = df.copy()
    df["Father Sim"] = df.apply(
        lambda r: round(father_similarity(r["Current Father"], r["Prev Father"]), 2),
        axis=1)
    df["Father Match"] = df["Father Sim"].apply(
        lambda s: "SAME" if s >= father_th else "DIFFERENT")

    def _status(r):
        if not (_norm(r["Current Father"]) and _norm(r["Prev Father"])
                and _norm(r["Current Name"])):
            return "INVALID"
        if r["Father Match"] == "DIFFERENT":
            return "IMPERSONATION"
        if _norm(r["Current Name"]) == _norm(r["Prev Name"]):
            return "SAME DETAILS"
        return "SIBLING/TWIN"

    df["Status"] = df.apply(_status, axis=1)
    return df


def classify_dedup(df, father_th):
    """Dedup pairs: mark a pair IMPERSONATION when the two father names differ."""
    df = df.copy()
    df["Father Sim"] = df.apply(
        lambda r: round(father_similarity(r["Current Father"], r["Prev Father"]), 2),
        axis=1)
    df["Father Match"] = df["Father Sim"].apply(
        lambda s: "SAME" if s >= father_th else "DIFFERENT")

    def _status(r):
        if not (_norm(r["Current Father"]) and _norm(r["Prev Father"])):
            return "INVALID"
        return "IMPERSONATION" if r["Father Match"] == "DIFFERENT" else "SIBLING/TWIN"

    df["Status"] = df.apply(_status, axis=1)
    return df


# --------------------------------------------------------------------------- #
# History — NEW vs OLD across live refreshes
#
# The source link is live: rows get appended over time. On each LOAD/REFRESH we
# diff the current record IDs against the snapshot from the PREVIOUS load:
#   NEW = signature absent from the previous snapshot (added since last refresh)
#   OLD = signature already present in the previous snapshot
# On the very first load there is no prior snapshot, so every row is NEW.
# The diff is computed ONCE per refresh (in the load block) and frozen, so it
# stays stable while you interact with filters/sliders.
# --------------------------------------------------------------------------- #
def _sigs(df, cols):
    """Build a per-row signature Series from the given id columns (vectorized)."""
    s = df[cols[0]].astype(str)
    for c in cols[1:]:
        s = s + "|" + df[c].astype(str)
    return s


def refresh_history(sigs, ns):
    """Diff signatures vs the previous snapshot, then advance the baseline.
    Namespaced by `ns` so each tab keeps its own history. Called once per load."""
    cur = set(sigs)
    bkey = f"{ns}_baseline"
    new = cur if bkey not in st.session_state else cur - st.session_state[bkey]
    st.session_state[f"{ns}_new"] = new
    st.session_state[bkey] = cur


def apply_record_status(df, sigs, ns):
    """Tag rows NEW/OLD from the frozen diff (safe to call on every rerun)."""
    new = st.session_state.get(f"{ns}_new", set())
    df = df.copy()
    df["Record Status"] = ["NEW" if s in new else "OLD" for s in sigs]
    return df


def _row_style(row):
    if row.get("Father Match") == "DIFFERENT":
        return ["background-color: #fde2e2"] * len(row)        # red = impersonation
    if row.get("Record Status") == "NEW":
        return ["background-color: #e6f7e6"] * len(row)        # green = newly added
    if row.get("Status") == "SAME DETAILS":
        return ["background-color: #e3f0ff"] * len(row)        # blue
    return [""] * len(row)


def render_report_tab(ns, default_url, parse_fn, classify_fn, sig_cols,
                      display_cols, status_metrics, help_text):
    """Generic report tab: load a live URL, classify, diff NEW/OLD, show table."""
    st.caption(help_text)

    with st.container(border=True):
        st.markdown("**HTML REPORT URL**")
        url = st.text_input("url", value=default_url, key=f"{ns}_url",
                            label_visibility="collapsed")
        c1, c2 = st.columns(2)
        load = c1.button("▶ LOAD / REFRESH", use_container_width=True,
                         type="primary", key=f"{ns}_load")
        if c2.button("↻ RESET HISTORY", use_container_width=True, key=f"{ns}_reset"):
            for k in (f"{ns}_baseline", f"{ns}_new", f"{ns}_data"):
                st.session_state.pop(k, None)
            st.success("History reset — next load is a fresh baseline (all NEW).")

    dkey = f"{ns}_data"
    if not (load or dkey in st.session_state):
        st.info("Paste a report URL and click **LOAD / REFRESH** to begin.")
        return

    if load:
        try:
            with st.spinner("Fetching and parsing report…"):
                rows = parse_fn(fetch_html(url))
            if not rows:
                st.error("No records found. Is the URL a valid report of this type?")
                return
            df0 = pd.DataFrame(rows)
            st.session_state[dkey] = df0
            refresh_history(_sigs(df0, sig_cols), ns)   # diff vs previous snapshot
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to load report: {exc}")
            return

    df = classify_fn(st.session_state[dkey], st.session_state["father_th"])
    df = apply_record_status(df, _sigs(df, sig_cols), ns)

    # ---- Metric cards ----------------------------------------------------- #
    total = len(df)
    new_cnt = int((df["Record Status"] == "NEW").sum())
    st.markdown(
        f'<div class="status-badge">📡 DETECTED &nbsp;·&nbsp; '
        f'<span class="pill-new">🟢 {new_cnt} NEW</span> &nbsp;·&nbsp; '
        f'<span class="pill-old">⚪ {total - new_cnt} OLD</span></div>',
        unsafe_allow_html=True)

    cards = [("TOTAL", total)] + [
        (label, int((df["Status"] == value).sum())) for label, value in status_metrics]
    html = '<div class="metric-row">'
    for label, val in cards:
        color = _metric_color(label)
        html += (f'<div class="metric-card" style="border-top-color:{color}">'
                 f'<div class="metric-label">{label}</div>'
                 f'<div class="metric-value" style="color:{color}">{val}</div></div>')
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

    # ---- Filters ---------------------------------------------------------- #
    f = st.columns(2)
    status_f = f[0].selectbox("STATUS FILTER", ["ALL"] + sorted(df["Status"].unique()),
                              key=f"{ns}_statusf")
    rec_f = f[1].selectbox("RECORD STATUS", ["ALL", "NEW", "OLD"], key=f"{ns}_recf")
    only_new = st.checkbox("🟢 Show only NEW records (added since last refresh)",
                           value=False, key=f"{ns}_onlynew")

    view = df.copy()
    if status_f != "ALL":
        view = view[view["Status"] == status_f]
    if rec_f != "ALL":
        view = view[view["Record Status"] == rec_f]
    if only_new:
        view = view[view["Record Status"] == "NEW"]

    st.caption(f"Showing **{len(view)}** of **{total}** records")

    rename = {src: dst for src, dst in display_cols}
    view = view.rename(columns=rename)[[dst for _, dst in display_cols]]
    view = view.reset_index(drop=True)
    view.index += 1

    st.dataframe(view.style.apply(_row_style, axis=1),
                 use_container_width=True, height=560)

    imp_view = view[view["Status"] == "IMPERSONATION"]
    imp_new_view = imp_view[imp_view["Record Status"] == "NEW"]
    d1, d2 = st.columns(2)
    d1.download_button(
        f"⬇ Download ALL IMPERSONATION records ({len(imp_view)}) as CSV",
        data=imp_view.to_csv(index=False).encode(),
        file_name=f"{ns}_impersonation_records.csv", mime="text/csv",
        use_container_width=True, key=f"{ns}_dl_all")
    d2.download_button(
        f"⬇ Download NEW IMPERSONATION records ({len(imp_new_view)}) as CSV",
        data=imp_new_view.to_csv(index=False).encode(),
        file_name=f"{ns}_impersonation_new_records.csv", mime="text/csv",
        use_container_width=True, key=f"{ns}_dl_new")


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
inject_css()
st.markdown(
    '<div class="app-header"><h1>🔍 Duplicate Detection System</h1>'
    '<p>Biometric impersonation analysis — flags candidates whose father name '
    'differs between matched records. Live reports, refreshed on demand.</p></div>',
    unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙ Matching threshold")
    st.session_state["father_th"] = st.slider(
        "Father-name similarity threshold", 0.0, 1.0, 0.60, 0.01,
        help="Below this similarity, two father names count as DIFFERENT.")
    st.caption("Below this similarity, the two father names are DIFFERENT "
               "→ flagged as IMPERSONATION.")

PREV_DISPLAY = [
    ("Current ID", "Current Enroll No"), ("Current Name", "Current Name"),
    ("Current Father", "Current Father"), ("Current DOB", "Current DOB"),
    ("Prev ID", "Prev Enroll No"), ("Prev Name", "Prev Name"),
    ("Prev Father", "Prev Father"), ("Prev DOB", "Prev DOB"),
    ("Face Score", "Face Score"), ("Cross Score", "Cross Score"),
    ("Bio Score", "Bio Score"), ("Father Sim", "Father Sim"),
    ("Father Match", "Father Match"), ("Status", "Status"),
    ("Record Status", "Record Status"),
]
DEDUP_DISPLAY = [
    ("Current Enroll", "Current Enroll No"), ("Current Name", "Current Name"),
    ("Current Father", "Current Father"), ("Current DOB", "Current DOB"),
    ("Current Shift", "Current Shift"),
    ("Prev Enroll", "Prev Enroll No"), ("Prev Name", "Prev Name"),
    ("Prev Father", "Prev Father"), ("Prev DOB", "Prev DOB"),
    ("Prev Shift", "Prev Shift"),
    ("Enroll Score", "Enroll Score"), ("App Score", "App Score"),
    ("Bio Score", "Bio Score"), ("Bio Verdict", "Bio Verdict"),
    ("Father Sim", "Father Sim"), ("Father Match", "Father Match"),
    ("Status", "Status"), ("Record Status", "Record Status"),
]

tab_prev, tab_dedup = st.tabs(["📋 PREV REPORT", "🔁 DEDUP"])

with tab_prev:
    render_report_tab(
        ns="prev", default_url=DEFAULT_URL,
        parse_fn=parse_report, classify_fn=classify,
        sig_cols=["Current ID", "Prev ID"], display_cols=PREV_DISPLAY,
        status_metrics=[("🚨 IMPERSONATION", "IMPERSONATION"),
                        ("SAME DETAILS", "SAME DETAILS"),
                        ("SIBLING/TWIN", "SIBLING/TWIN"), ("INVALID", "INVALID")],
        help_text="Flags candidates whose **current** father name differs from "
                  "their **previous-exam** father name — a strong impersonation signal.")

with tab_dedup:
    render_report_tab(
        ns="dedup", default_url=DEFAULT_DEDUP_URL,
        parse_fn=parse_dedup_report, classify_fn=classify_dedup,
        sig_cols=["Current Enroll", "Prev Enroll"], display_cols=DEDUP_DISPLAY,
        status_metrics=[("🚨 IMPERSONATION", "IMPERSONATION"),
                        ("SIBLING/TWIN", "SIBLING/TWIN"), ("INVALID", "INVALID")],
        help_text="Pairwise dedup matches. Where the two candidates' **father "
                  "names differ**, the pair is flagged as **IMPERSONATION**.")
