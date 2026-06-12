# 🔍 Duplicate Detection System

A Streamlit web app that loads live **TrustView HTML reports** from a URL and **flags
records whose two father names differ** as IMPERSONATION. It has two tabs:

- **📋 PREV REPORT** — current-vs-previous-exam matches. Example URL:
  `https://trustview.in/dwnld/upprpb25_10%20Jun'26%20S1_repscoreprvgrp1.html`
- **🔁 DEDUP** — pairwise enroll-to-enroll matches within the current pool. Example URL:
  `https://trustview.in/dwnld/upprpb2510Jun%2726S1_dedup_.html`

Each tab keeps its own NEW/OLD history, so refreshing one doesn't affect the other.

## What it does

1. **Fetch & parse** the HTML report (each source row is expanded into one row per
   previous match).
2. Extract: Current Name / Father / DOB, Previous Name / Father / DOB, and the
   Face / Cross / Bio scores.
3. **Father Match** — fuzzy-compares current vs previous father name
   (`SAME` / `DIFFERENT`). Validated against the source report: it reproduces the
   original report's Father-Match column exactly.
4. **Status** — `IMPERSONATION` (different father), `SAME DETAILS`, `SIBLING/TWIN`,
   `INVALID`.
5. Metric cards, filters (status / father / record-status / min cross & bio score),
   **red-highlighted father-name mismatches**, NEW-vs-OLD history tracking, and a
   CSV download of the flagged records.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501, paste a report URL, and click **LOAD / REFRESH**.

## Deploy on Streamlit Community Cloud (free hosting)

1. Create a GitHub repo and push these files (`app.py`, `requirements.txt`,
   `README.md`, `.gitignore`).
2. Go to **https://share.streamlit.io** → **New app**.
3. Select your repo / branch, set **Main file path** to `app.py`, and **Deploy**.
4. You get a public URL like `https://<your-app>.streamlit.app`.

## Tuning

The sidebar exposes one threshold:

- **Father-name similarity threshold** (default `0.60`) — below this, two father
  names are treated as DIFFERENT (→ `IMPERSONATION`).
