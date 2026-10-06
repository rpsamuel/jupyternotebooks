"""
SEC Form 13F ingestion and whale-conviction scoring for WhaleWisdom 2.0.

Design goals
------------
* SEC quarterly Form 13F data sets are the source of truth.
* CUSIP is the canonical security identifier; ticker mapping is enrichment.
* Preserve manager, filing, report-quarter, and source provenance.
* Do not silently replace missing financial/holding data with zeros.
* Base implementation uses original 13F-HR filings. If amendments are present,
  they are flagged for review rather than silently merged.

Current complete comparison used by the notebook:
    2026-06-30 versus 2026-03-31
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd
import requests


SEC_13F_DATASETS = {
    "2026Q2": "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip",
    "2026Q1": "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip",
}

# Initial high-conviction manager set. Add/remove managers in one place.
# CIKs below are SEC filer identifiers.
DEFAULT_MANAGERS = pd.DataFrame(
    [
        {"manager": "Bridgewater Associates", "cik": "0001350694", "manager_weight": 1.00},
        {"manager": "Duquesne Family Office", "cik": "0001536411", "manager_weight": 1.15},
        {"manager": "Tiger Global Management", "cik": "0001167483", "manager_weight": 1.00},
    ]
)


@dataclass
class FilingQuarter:
    submission: pd.DataFrame
    infotable: pd.DataFrame


def _headers(user_agent: Optional[str] = None) -> Dict[str, str]:
    ua = user_agent or os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise ValueError(
            "Set SEC_USER_AGENT, for example: "
            "'WhaleWisdomResearch your-email@example.com'. "
            "SEC requests should identify the application/contact."
        )
    return {
        "User-Agent": ua,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def download_dataset(url: str, user_agent: Optional[str] = None, timeout: int = 120) -> bytes:
    response = requests.get(url, headers=_headers(user_agent), timeout=timeout)
    response.raise_for_status()
    return response.content


def _find_member(zf: zipfile.ZipFile, stem: str) -> str:
    wanted = stem.upper()
    matches = [
        name
        for name in zf.namelist()
        if name.upper().endswith(f"{wanted}.TSV")
        or name.upper().endswith(f"{wanted}.TXT")
    ]
    if not matches:
        raise FileNotFoundError(f"{stem} table not found in SEC 13F dataset")
    return matches[0]


def _read_table(zf: zipfile.ZipFile, stem: str) -> pd.DataFrame:
    member = _find_member(zf, stem)
    with zf.open(member) as fh:
        df = pd.read_csv(fh, sep="\t", dtype=str, low_memory=False)
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def load_quarter_from_bytes(blob: bytes) -> FilingQuarter:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        submission = _read_table(zf, "SUBMISSION")
        infotable = _read_table(zf, "INFOTABLE")
    return FilingQuarter(submission=submission, infotable=infotable)


def load_quarter(url: str, user_agent: Optional[str] = None) -> FilingQuarter:
    return load_quarter_from_bytes(download_dataset(url, user_agent=user_agent))


def _normalize_cik(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)


def prepare_submission(submission: pd.DataFrame) -> pd.DataFrame:
    s = submission.copy()
    s["CIK"] = _normalize_cik(s["CIK"])
    s["FILING_DATE"] = pd.to_datetime(s["FILING_DATE"], errors="coerce")
    s["PERIODOFREPORT"] = pd.to_datetime(s["PERIODOFREPORT"], errors="coerce")
    return s


def amendment_flags(submission: pd.DataFrame) -> pd.DataFrame:
    s = prepare_submission(submission)
    amended = s[s["SUBMISSIONTYPE"].astype(str).str.upper().eq("13F-HR/A")].copy()
    if amended.empty:
        return pd.DataFrame(columns=["CIK", "PERIODOFREPORT", "amendment_present"])
    out = amended[["CIK", "PERIODOFREPORT"]].drop_duplicates()
    out["amendment_present"] = True
    return out


def select_manager_filings(
    submission: pd.DataFrame,
    managers: pd.DataFrame = DEFAULT_MANAGERS,
    period: Optional[str] = None,
) -> pd.DataFrame:
    """Return one base 13F-HR accession per selected manager and report period."""
    s = prepare_submission(submission)
    m = managers.copy()
    m["cik"] = _normalize_cik(m["cik"])

    # Use holdings reports only. Notices have no information table.
    base = s[s["SUBMISSIONTYPE"].astype(str).str.upper().eq("13F-HR")].copy()
    if period is not None:
        p = pd.Timestamp(period)
        base = base[base["PERIODOFREPORT"].eq(p)]

    base = base.merge(m, left_on="CIK", right_on="cik", how="inner")
    if base.empty:
        return base

    # Defensive de-duplication in case the data set contains multiple base filings.
    base = (
        base.sort_values("FILING_DATE")
        .groupby(["CIK", "PERIODOFREPORT"], as_index=False)
        .tail(1)
    )

    flags = amendment_flags(s)
    base = base.merge(flags, on=["CIK", "PERIODOFREPORT"], how="left")
    base["amendment_present"] = base["amendment_present"].fillna(False)
    return base


def holdings_for_filings(
    infotable: pd.DataFrame,
    filings: pd.DataFrame,
) -> pd.DataFrame:
    """Attach SEC information-table holdings to selected manager filings."""
    if filings.empty:
        return pd.DataFrame()

    cols = [
        "ACCESSION_NUMBER",
        "NAMEOFISSUER",
        "TITLEOFCLASS",
        "CUSIP",
        "VALUE",
        "SSHPRNAMT",
        "SSHPRNAMTTYPE",
        "PUTCALL",
    ]
    available = [c for c in cols if c in infotable.columns]
    h = infotable[available].copy()

    h["VALUE"] = pd.to_numeric(h.get("VALUE"), errors="coerce")
    h["SSHPRNAMT"] = pd.to_numeric(h.get("SSHPRNAMT"), errors="coerce")

    filing_cols = [
        "ACCESSION_NUMBER",
        "CIK",
        "PERIODOFREPORT",
        "FILING_DATE",
        "manager",
        "manager_weight",
        "amendment_present",
    ]
    h = h.merge(filings[filing_cols], on="ACCESSION_NUMBER", how="inner")

    # VALUE in the SEC flattened data set is market value in $ thousands.
    h["market_value_usd"] = h["VALUE"] * 1000.0

    # Exclude options from ordinary long-equity conviction by default.
    h["is_option"] = h.get("PUTCALL", pd.Series(index=h.index, dtype=object)).notna()
    h["CUSIP"] = h["CUSIP"].astype(str).str.strip().str.upper()
    return h


def aggregate_manager_positions(holdings: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate duplicate information-table rows into manager/security positions.

    Multiple rows can exist for one security due to class/discretion/reporting detail.
    """
    if holdings.empty:
        return holdings.copy()

    long_h = holdings[~holdings["is_option"]].copy()
    keys = [
        "CIK",
        "manager",
        "manager_weight",
        "PERIODOFREPORT",
        "CUSIP",
        "NAMEOFISSUER",
        "TITLEOFCLASS",
        "amendment_present",
    ]
    out = (
        long_h.groupby(keys, dropna=False, as_index=False)
        .agg(
            market_value_usd=("market_value_usd", "sum"),
            shares=("SSHPRNAMT", "sum"),
        )
    )

    totals = (
        out.groupby(["CIK", "PERIODOFREPORT"], as_index=False)["market_value_usd"]
        .sum()
        .rename(columns={"market_value_usd": "manager_13f_value_usd"})
    )
    out = out.merge(totals, on=["CIK", "PERIODOFREPORT"], how="left")
    out["portfolio_weight"] = out["market_value_usd"] / out["manager_13f_value_usd"]
    return out


def compare_quarters(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Compare manager/security positions using CUSIP as the canonical identifier."""
    c = current.copy()
    p = previous.copy()

    c = c.rename(
        columns={
            "market_value_usd": "current_value_usd",
            "shares": "current_shares",
            "portfolio_weight": "current_portfolio_weight",
            "NAMEOFISSUER": "current_issuer",
            "TITLEOFCLASS": "current_class",
            "amendment_present": "current_amendment_present",
        }
    )
    p = p.rename(
        columns={
            "market_value_usd": "previous_value_usd",
            "shares": "previous_shares",
            "portfolio_weight": "previous_portfolio_weight",
            "NAMEOFISSUER": "previous_issuer",
            "TITLEOFCLASS": "previous_class",
            "amendment_present": "previous_amendment_present",
        }
    )

    keep = ["CIK", "manager", "manager_weight", "CUSIP"]
    ccols = keep + [
        "current_issuer",
        "current_class",
        "current_value_usd",
        "current_shares",
        "current_portfolio_weight",
        "current_amendment_present",
    ]
    pcols = keep + [
        "previous_issuer",
        "previous_class",
        "previous_value_usd",
        "previous_shares",
        "previous_portfolio_weight",
        "previous_amendment_present",
    ]

    x = c[ccols].merge(p[pcols], on=keep, how="outer")
    x["issuer"] = x["current_issuer"].fillna(x["previous_issuer"])
    x["title_of_class"] = x["current_class"].fillna(x["previous_class"])

    cur = x["current_shares"].fillna(0.0)
    prev = x["previous_shares"].fillna(0.0)
    x["position_status"] = np.select(
        [
            (prev == 0) & (cur > 0),
            (prev > 0) & (cur == 0),
            (cur > prev) & (prev > 0),
            (cur < prev) & (cur > 0),
        ],
        ["NEW", "EXITED", "INCREASED", "REDUCED"],
        default="UNCHANGED",
    )
    x["share_change_pct"] = np.where(
        prev > 0,
        (cur - prev) / prev,
        np.where(cur > 0, np.inf, np.nan),
    )
    x["weight_change"] = (
        x["current_portfolio_weight"].fillna(0)
        - x["previous_portfolio_weight"].fillna(0)
    )
    x["amendment_review"] = (
        x["current_amendment_present"].fillna(False)
        | x["previous_amendment_present"].fillna(False)
    )
    return x


def score_whale_conviction(changes: pd.DataFrame) -> pd.DataFrame:
    """
    Convert manager-level changes into a 0-100 security conviction score.

    Components:
      ownership breadth      25%
      weighted concentration 30%
      accumulation breadth   25%
      new-position breadth   10%
      average weight change  10%

    Scores are cross-sectional for the selected manager set, not absolute truths.
    """
    if changes.empty:
        return pd.DataFrame()

    x = changes.copy()
    current = x[x["current_value_usd"].fillna(0) > 0].copy()

    def _weighted_mean(g: pd.DataFrame, value_col: str) -> float:
        vals = pd.to_numeric(g[value_col], errors="coerce")
        weights = pd.to_numeric(g["manager_weight"], errors="coerce").fillna(1.0)
        mask = vals.notna()
        if not mask.any():
            return np.nan
        return float(np.average(vals[mask], weights=weights[mask]))

    rows = []
    all_cusips = sorted(x["CUSIP"].dropna().unique())
    manager_count = max(x["CIK"].nunique(), 1)

    for cusip in all_cusips:
        g = x[x["CUSIP"].eq(cusip)]
        gc = g[g["current_value_usd"].fillna(0) > 0]
        holders = gc["CIK"].nunique()
        accumulating = g["position_status"].isin(["NEW", "INCREASED"]).sum()
        new_count = g["position_status"].eq("NEW").sum()

        rows.append(
            {
                "CUSIP": cusip,
                "issuer": g["issuer"].dropna().iloc[0] if g["issuer"].notna().any() else "",
                "title_of_class": g["title_of_class"].dropna().iloc[0] if g["title_of_class"].notna().any() else "",
                "funds_holding": holders,
                "ownership_breadth": holders / manager_count,
                "funds_accumulating": accumulating,
                "accumulation_breadth": accumulating / manager_count,
                "new_positions": new_count,
                "new_position_breadth": new_count / manager_count,
                "weighted_avg_portfolio_weight": _weighted_mean(gc, "current_portfolio_weight") if not gc.empty else 0.0,
                "weighted_avg_weight_change": _weighted_mean(g, "weight_change"),
                "total_current_value_usd": gc["current_value_usd"].sum(),
                "amendment_review": bool(g["amendment_review"].any()),
            }
        )

    s = pd.DataFrame(rows)

    def pct(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce").rank(pct=True, method="average").fillna(0) * 100

    s["breadth_score"] = s["ownership_breadth"] * 100
    s["concentration_score"] = pct(s["weighted_avg_portfolio_weight"])
    s["accumulation_score"] = s["accumulation_breadth"] * 100
    s["new_position_score"] = s["new_position_breadth"] * 100
    s["weight_change_score"] = pct(s["weighted_avg_weight_change"])

    s["whale_score"] = (
        0.25 * s["breadth_score"]
        + 0.30 * s["concentration_score"]
        + 0.25 * s["accumulation_score"]
        + 0.10 * s["new_position_score"]
        + 0.10 * s["weight_change_score"]
    ).clip(0, 100)

    # Data quality warning rather than silent correction.
    s["whale_score_status"] = np.where(
        s["amendment_review"],
        "REVIEW_AMENDMENT",
        "OK",
    )
    return s.sort_values("whale_score", ascending=False).reset_index(drop=True)


def attach_ticker_mapping(
    whale_scores: pd.DataFrame,
    mapping: pd.DataFrame,
) -> pd.DataFrame:
    """
    Attach ticker symbols using an explicit CUSIP→ticker mapping.

    Required mapping columns: CUSIP, ticker.
    This function deliberately does no fuzzy issuer-name matching.
    """
    m = mapping.copy()
    m.columns = [str(c).strip() for c in m.columns]
    required = {"CUSIP", "ticker"}
    missing = required.difference(m.columns)
    if missing:
        raise ValueError(f"ticker mapping missing columns: {sorted(missing)}")
    m["CUSIP"] = m["CUSIP"].astype(str).str.strip().str.upper()
    m["ticker"] = m["ticker"].astype(str).str.strip().str.upper()
    return whale_scores.merge(m[["CUSIP", "ticker"]].drop_duplicates(), on="CUSIP", how="left")


def build_whale_scores(
    current: FilingQuarter,
    previous: FilingQuarter,
    managers: pd.DataFrame = DEFAULT_MANAGERS,
    current_period: str = "2026-06-30",
    previous_period: str = "2026-03-31",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    cur_filings = select_manager_filings(current.submission, managers, current_period)
    prev_filings = select_manager_filings(previous.submission, managers, previous_period)

    cur_pos = aggregate_manager_positions(
        holdings_for_filings(current.infotable, cur_filings)
    )
    prev_pos = aggregate_manager_positions(
        holdings_for_filings(previous.infotable, prev_filings)
    )
    changes = compare_quarters(cur_pos, prev_pos)
    scores = score_whale_conviction(changes)
    return scores, changes


if __name__ == "__main__":
    print("WhaleWisdom 13F module loaded.")
    print("Set SEC_USER_AGENT before downloading SEC data.")
    print("Current supported comparison: 2026Q2 vs 2026Q1.")
