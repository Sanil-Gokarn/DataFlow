"""DataFlow: find what's wrong with a CSV, approve the fixes you want, download the clean version.

Run with:  streamlit run app.py
"""
import hashlib
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from dataflow import (apply_fixes, build_markdown, build_tasks, compare, load_csv, make_client, profile,
                      propose_fixes, run_tasks, summarise, to_numeric)
from dataflow.ai import CONFIDENT

st.set_page_config(page_title="DataFlow", page_icon="🧭", layout="wide")

SAMPLE = Path(__file__).parent / "sample_data" / "nhs_appointments_dirty.csv"
ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
MAX_ROWS_SHOWN = 50
EDIT_LIMIT = 200

# Public mode is for a shared web deployment (the Dockerfile turns it on). It never uses the server's own API key,
# caps file size, and forgets uploaded data quickly.
PUBLIC = os.environ.get("DATAFLOW_PUBLIC") == "1"
MAX_PUBLIC_ROWS = int(os.environ.get("DATAFLOW_MAX_ROWS", "50000"))
CACHE = dict(ttl=900, max_entries=4) if PUBLIC else {}


# ------------------------------------------------------------------ cached work
@st.cache_data(show_spinner="Checking your data…", **CACHE)
def run(data: bytes):
    df = load_csv(data)
    report = profile(df)
    return df, report, propose_fixes(df, report)


@st.cache_data(show_spinner="Applying approved changes…", **CACHE)
def run_cleaned(data: bytes, fixes: tuple):
    df, _, _ = run(data)
    cleaned, log = apply_fixes(df, list(fixes))
    return cleaned, profile(cleaned), log


@st.cache_data(show_spinner=False, **CACHE)
def ai_tasks(data: bytes):
    df, report, _ = run(data)
    return build_tasks(df, report)


def pretty(kind: str) -> str:
    return kind.replace("_", " ").capitalize()


# ------------------------------------------------------------------ callbacks (run before the page redraws)
def apply_selected(fixes: tuple, label: str):
    if fixes:
        st.session_state.applied.update({f.id: f for f in fixes})
        st.session_state.batches.append({"ids": tuple(f.id for f in fixes), "label": label})
        st.session_state.view = "Cleaned data"
        st.session_state.summary = None


def undo_batch(index: int):
    batch = st.session_state.batches.pop(index)
    for fid in batch["ids"]:
        st.session_state.applied.pop(fid, None)
    st.session_state.summary = None
    if not st.session_state.applied:
        st.session_state.view = "Original data"


def undo_all():
    st.session_state.applied, st.session_state.batches, st.session_state.summary = {}, [], None
    st.session_state.view = "Original data"


# ------------------------------------------------------------------ sidebar / input
st.sidebar.title("🧭 DataFlow")
st.sidebar.caption("Check a dataset, approve the fixes you want, and download the cleaned version.")
uploaded = st.sidebar.file_uploader("Upload a CSV file", type=["csv", "tsv", "txt"])
if SAMPLE.exists() and st.sidebar.button("Try the sample dataset (fake NHS-style data)"):
    st.session_state["use_sample"] = True
api_key = st.sidebar.text_input("Claude API key (optional)", type="password",
                                help="Used only for the AI review tab and kept in this session's memory, never saved. "
                                     + ("This server has no key of its own, so AI review uses yours."
                                        if PUBLIC else "You can also set the ANTHROPIC_API_KEY environment variable."))
client = make_client(api_key or None, use_env=not PUBLIC)
if PUBLIC:
    st.sidebar.warning("Public demo: files are processed in memory and not saved, but please don't upload "
                       "personal or confidential data. Use the sample dataset or your own non-sensitive files.")
if client.mode == "claude":
    st.sidebar.success("AI review: using Claude")
else:
    st.sidebar.info("AI review: demo mode (no key). A small built-in word list stands in for the AI.")

if uploaded is not None:
    st.session_state["use_sample"] = False
    data, source_name = uploaded.getvalue(), uploaded.name
elif st.session_state.get("use_sample"):
    data, source_name = SAMPLE.read_bytes(), SAMPLE.name
else:
    st.title("🧭 DataFlow")
    st.write("Upload a CSV in the sidebar to get a full health check, or try the sample dataset to see what it finds.")
    st.info("Your data is never changed until you approve specific fixes, and every change can be undone.")
    st.stop()

if PUBLIC and data.count(b"\n") > MAX_PUBLIC_ROWS + 1:
    st.error(f"This public demo is limited to {MAX_PUBLIC_ROWS:,} rows. Please upload a smaller file.")
    st.stop()

# a new file starts a fresh session of approvals
data_id = hashlib.md5(data).hexdigest()
if st.session_state.get("data_id") != data_id:
    st.session_state.update(data_id=data_id, applied={}, batches=[], view="Original data", ai=None, summary=None)

try:
    df, report, groups = run(data)
except Exception as exc:  # unreadable / ragged file
    st.error(f"Couldn't read that file as a table: {exc}")
    st.stop()

applied = st.session_state.applied
if applied:
    cleaned, clean_report, change_log = run_cleaned(data, tuple(applied[k] for k in sorted(applied)))
else:
    cleaned, clean_report, change_log = df, report, None

# ------------------------------------------------------------------ header
st.title("🧭 DataFlow")
st.caption(f"{source_name} · {report.n_rows:,} rows × {report.n_cols} columns (original)")
if applied:
    st.radio("Viewing", ["Original data", "Cleaned data"], key="view", horizontal=True)
view_clean = bool(applied) and st.session_state.get("view") == "Cleaned data"
vdf, vreport = (cleaned, clean_report) if view_clean else (df, report)
if view_clean:
    st.caption("Showing the cleaned data. Row numbers below refer to the cleaned file, not the original.")

by_sev = {s: sum(1 for i in vreport.issues if i.severity == s) for s in ICON}
c = st.columns(5)
c[0].metric("Quality score", f"{vreport.score}%", delta=f"{vreport.score - report.score:+.1f}" if view_clean else None)
c[1].metric("Rows with no problems", f"{vreport.clean_row_pct}%",
            delta=f"{vreport.clean_row_pct - report.clean_row_pct:+.1f}" if view_clean else None)
c[2].metric("🔴 High", by_sev["high"])
c[3].metric("🟠 Medium", by_sev["medium"])
c[4].metric("🟡 Low", by_sev["low"])
with st.expander("How is the score worked out?"):
    st.write(
        "The quality score is the share of cells that aren't flagged by a high or medium issue. 'Rows with no "
        "problems' is the share of rows with no flagged cell at all. Low-severity items and layout patterns such as "
        "merged cells are shown but not counted. Use it to compare before and after cleaning, not as an absolute grade."
    )


def render_groups(group_list, prefix):
    """Show proposed fixes with tick boxes. Returns (selected fixes, summary text). Nothing is applied here."""
    selected, summary = [], []
    for g in group_list:
        remaining = [f for f in g.fixes if f.id not in applied]
        if not remaining:
            st.success(f"✅ {g.title}: applied")
            continue
        with st.expander(f"{g.title} · {len(remaining):,} changes"):
            st.write(g.description)
            if g.judgement and g.source == "rules":
                st.caption("⚖️ This is a guess about the file's layout, so it isn't pre-ticked. Check the rows first.")
            include = st.checkbox("Include this group", value=g.default_on, key=f"inc_{prefix}{g.key}")
            shown_fixes = remaining[:EDIT_LIMIT]
            table = pd.DataFrame({
                "Apply": [f.confidence is None or f.confidence >= CONFIDENT for f in shown_fixes],
                "row in file": [f.row + 2 for f in shown_fixes],
                "column": ["(whole row)" if f.column == "*" else f.column for f in shown_fixes],
                "before": [f.old for f in shown_fixes],
                "after": [f.new if f.action == "set" else "(row removed)" for f in shown_fixes],
                "why": [f.reason for f in shown_fixes]})
            disabled = ["row in file", "column", "before", "after", "why"]
            if g.source == "ai":
                table["confidence"] = [f"{f.confidence:.0%}" for f in shown_fixes]
                disabled.append("confidence")
            edited = st.data_editor(table, key=f"ed_{prefix}{g.key}_{len(applied)}", hide_index=True,
                                    width="stretch", disabled=disabled)
            rejected = {shown_fixes[i].id for i, ok in enumerate(edited["Apply"]) if not ok}
            if len(remaining) > EDIT_LIMIT:
                st.caption(f"Showing the first {EDIT_LIMIT} of {len(remaining):,}. The other "
                           f"{len(remaining) - EDIT_LIMIT:,} follow the group tick box.")
            if include:
                chosen = [f for f in remaining if f.id not in rejected]
                selected += chosen
                if chosen:
                    summary.append(f"{g.title.lower()} ({len(chosen):,})")
    return selected, summary


def apply_button(selected, summary, key):
    ids = tuple(selected)
    st.button(f"Apply {len(ids):,} selected change{'s' if len(ids) != 1 else ''}", type="primary", disabled=not ids,
              on_click=apply_selected, args=(ids, "; ".join(summary)), key=key)


tab_issues, tab_fix, tab_ai, tab_results, tab_cols, tab_data = st.tabs(
    ["Issues", "Fix", "AI review", f"Results{' ✓' if applied else ''}", "Columns", "Data preview"])

# ------------------------------------------------------------------ issues
with tab_issues:
    f1, f2, f3 = st.columns([2, 2, 2])
    sev_pick = f1.multiselect("Severity", list(ICON), default=list(ICON))
    kind_pick = f2.multiselect("Type", sorted({i.kind for i in vreport.issues}), format_func=pretty)
    col_pick = f3.multiselect("Column", sorted({i.column for i in vreport.issues if i.column not in ("", "*")}))
    only_judgement = st.checkbox("Only show issues that need a human (or AI) decision")

    shown = [i for i in vreport.issues if i.severity in sev_pick and (not kind_pick or i.kind in kind_pick)
             and (not col_pick or i.column in col_pick) and (not only_judgement or i.needs_judgement)]
    st.write(f"Showing {len(shown)} of {len(vreport.issues)} issues")

    if vreport.issues:
        export = pd.DataFrame([
            {"severity": i.severity, "type": i.kind, "column": i.column, "rows_affected": i.count,
             "message": i.message, "suggestion": i.suggestion,
             "file_rows": ", ".join(str(r + 2) for r in i.rows[:200])} for i in vreport.issues])
        st.download_button("Download issue list (CSV)", export.to_csv(index=False), "dataflow_issues.csv", "text/csv")

    for issue in shown:
        where = "whole row" if issue.column == "*" else issue.column or "table"
        label = f"{ICON[issue.severity]} {pretty(issue.kind)} · {where}" + (f" · {issue.count:,} rows" if issue.count else "")
        with st.expander(label):
            st.write(issue.message)
            if issue.suggestion:
                st.caption(f"Suggested: {issue.suggestion}")
            if issue.needs_judgement:
                st.caption("⚖️ Rules can't settle this one; it needs a decision.")
            if issue.examples:
                st.write("Examples: " + " · ".join(f"`{e}`" for e in issue.examples))
            if issue.rows:
                view = vdf.iloc[issue.rows[:MAX_ROWS_SHOWN]].copy()
                view.index = [r + 2 for r in issue.rows[:MAX_ROWS_SHOWN]]
                view.index.name = "row in file"
                st.dataframe(view, width="stretch")
                if issue.count > MAX_ROWS_SHOWN:
                    st.caption(f"Showing the first {MAX_ROWS_SHOWN} of {issue.count:,} affected rows.")

# ------------------------------------------------------------------ fix (rule-based)
with tab_fix:
    st.info("Nothing changes until you press **Apply**. Tick or untick whole groups, or individual rows, and "
            "everything you apply can be undone in the Results tab. Judgement calls (typos, nicknames, extreme "
            "values) are in the **AI review** tab instead.")
    if not groups:
        st.success("No automatic fixes are available for this file.")
    sel, summ = render_groups(groups, "r_")
    apply_button(sel, summ, "apply_rules")

# ------------------------------------------------------------------ AI review
with tab_ai:
    tasks = ai_tasks(data)
    if client.mode == "claude":
        st.success(f"Connected: suggestions will come from Claude ({client.model}).")
    else:
        st.warning("**Demo mode.** No API key is set, so a few fixed rules and a tiny word list (nicknames like "
                   "'Brum') stand in for the AI. They follow the same flow, so you can try everything. Add a key in "
                   "the sidebar for real Claude suggestions" + (" (your own key: this server doesn't have one)." if PUBLIC else "."))
    if not tasks:
        st.success("Nothing in this file needs AI judgement.")
    else:
        st.write(f"{len(tasks)} question(s) to ask about the leftovers rules can't settle: " +
                 ", ".join(f"{t.kind.replace('_', ' ')} in `{t.column}`" for t in tasks) + ".")
        with st.expander("Exactly what would be sent"):
            st.caption("Only column summaries and the unusual values themselves are sent: never whole rows or other "
                       "columns. Nothing is sent until you press the button below.")
            for t in tasks:
                st.json(t.payload, expanded=False)
        rule_cells = {(f.row, f.column) for g in groups for f in g.fixes if f.action == "set"}
        rule_rows = {f.row for g in groups for f in g.fixes if f.action == "drop_row"}
        if st.button("Ask Claude" if client.mode == "claude" else "Run demo suggestions", type="primary"):
            with st.spinner("Thinking…"):
                st.session_state.ai = run_tasks(df, tasks, client, rule_cells, rule_rows)
        ai = st.session_state.ai
        if ai:
            st.caption(f"{ai.calls} call(s) made · mode: {ai.mode}")
            for e in ai.errors:
                st.error(e)
            if ai.dropped:
                with st.expander(f"⚠️ {len(ai.dropped)} suggestion(s) were thrown away by the safety checks"):
                    for d in ai.dropped:
                        st.write("• " + d)
            if ai.notes:
                with st.expander(f"📝 {len(ai.notes)} value(s) the AI would leave alone or wants you to look at", expanded=True):
                    for n in ai.notes:
                        st.write(f"• **{n.column}**: {n.message}")
            if not ai.groups:
                st.info("The AI didn't propose any changes it was willing to make.")
            sel, summ = render_groups(ai.groups, "a_")
            apply_button(sel, summ, "apply_ai")

# ------------------------------------------------------------------ results
with tab_results:
    if not applied:
        st.info("No changes applied yet. Choose fixes in the Fix or AI review tab and press Apply.")
    else:
        m = st.columns(4)
        m[0].metric("Quality score", f"{clean_report.score}%", f"{clean_report.score - report.score:+.1f} vs original")
        m[1].metric("Rows with no problems", f"{clean_report.clean_row_pct}%",
                    f"{clean_report.clean_row_pct - report.clean_row_pct:+.1f} vs original")
        m[2].metric("Rows", f"{clean_report.n_rows:,}", f"{clean_report.n_rows - report.n_rows:+,} vs original",
                    delta_color="off")
        m[3].metric("Changes made", f"{len(change_log):,}")

        st.subheader("Problems before and after")
        st.dataframe(compare(report, clean_report), hide_index=True, width="stretch")
        st.caption("Problems that remain are ones DataFlow didn't try to fix, or that need your decision.")

        st.subheader("Plain-English summary")
        if st.button("Write a summary" + (" with Claude" if client.mode == "claude" else " (demo template)")):
            with st.spinner("Writing…"):
                try:
                    st.session_state.summary = summarise(client, report, clean_report, change_log)
                except Exception as exc:
                    st.error(f"Couldn't write the summary: {exc}")
        if st.session_state.summary:
            st.write(st.session_state.summary)

        st.subheader("Approved batches")
        for n, b in reversed(list(enumerate(st.session_state.batches))):
            left, right = st.columns([6, 1])
            left.write(f"**Batch {n + 1}** · {len(b['ids']):,} changes: {b['label']}")
            right.button("Undo", key=f"undo_{n}", on_click=undo_batch, args=(n,))
        st.button("Undo everything", on_click=undo_all)

        st.subheader("Download")
        stem = Path(source_name).stem
        d = st.columns(3)
        d[0].download_button("Cleaned data (CSV)", cleaned.to_csv(index=False), f"{stem}_cleaned.csv", "text/csv",
                             type="primary")
        d[1].download_button("Change log (CSV)", change_log.to_csv(index=False), f"{stem}_change_log.csv", "text/csv")
        d[2].download_button("Summary report (Markdown)",
                             build_markdown(source_name, report, clean_report, change_log, st.session_state.summary),
                             f"{stem}_report.md", "text/markdown")

        st.subheader("Change log")
        st.dataframe(change_log, hide_index=True, width="stretch")

# ------------------------------------------------------------------ columns
with tab_cols:
    table = pd.DataFrame([
        {"column": cp.name, "role": cp.role, "missing %": cp.pct_missing, "distinct values": cp.n_unique,
         "range": f"{cp.stats['min']} → {cp.stats['max']}" if "min" in cp.stats else "",
         "issues": sum(1 for i in vreport.issues if i.column == cp.name)} for cp in vreport.columns])
    st.dataframe(table, hide_index=True, width="stretch")

    pick = st.selectbox("Look closer at a column", [cp.name for cp in vreport.columns])
    cp = next(x for x in vreport.columns if x.name == pick)
    left, right = st.columns(2)
    with left:
        st.write(f"**{cp.name}**: looks like {cp.role} ({cp.dtype})")
        if cp.missing_breakdown:
            st.write("Missing values: " + ", ".join(f"`{k}` ×{v}" for k, v in cp.missing_breakdown.items()))
        if cp.stats:
            st.json(cp.stats, expanded=True)
    with right:
        if cp.dtype == "numeric":
            x = to_numeric(vdf[cp.name].str.strip()).dropna()
            if len(x):
                counts, edges = np.histogram(x, bins=min(30, max(5, int(np.sqrt(len(x))))))
                st.caption("Distribution")
                st.bar_chart(pd.DataFrame({"count": counts}, index=[f"{e:,.0f}" for e in edges[:-1]]))
        elif cp.top_values:
            st.caption("Most common values")
            st.bar_chart(pd.Series(dict(cp.top_values)))

# ------------------------------------------------------------------ preview
with tab_data:
    flagged = vreport.flagged_cells()
    only_bad = st.checkbox("Only rows with a flagged cell")
    mask = pd.DataFrame({name: pd.Series(vdf.index.isin(list(rows)), index=vdf.index) for name, rows in flagged.items()})
    pv = vdf[mask.any(axis=1)] if only_bad else vdf
    pv_mask = mask.loc[pv.index].head(500)
    pv = pv.head(500)
    pv.index, pv_mask.index = pv.index + 2, pv_mask.index + 2
    pv.index.name = "row in file"
    styled = pv.style.apply(lambda d: np.where(pv_mask, "background-color: #ffd9d9; color: #7a0000", ""), axis=None)
    st.caption(f"Flagged cells are highlighted. Showing the first {len(pv):,} rows.")
    st.dataframe(styled, width="stretch")
