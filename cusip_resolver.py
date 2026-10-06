"""
CUSIP -> ticker enrichment for WhaleWisdom 2.0 using OpenFIGI.

The SEC 13F data remains the holdings source of truth. OpenFIGI is used only
to map canonical CUSIPs to market symbols and FIGIs.

Design:
- explicit ID_CUSIP requests
- batched requests with rate-limit awareness
- optional API key via OPENFIGI_API_KEY
- cache mappings to CSV
- preserve unresolved / ambiguous mappings
- never use fuzzy issuer-name guessing
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd
import requests


OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"


def _headers(api_key: Optional[str] = None) -> dict:
    key = api_key or os.environ.get("OPENFIGI_API_KEY")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    return headers


def _normalize_cusips(cusips: Iterable[str]) -> List[str]:
    out = []
    for c in cusips:
        if pd.isna(c):
            continue
        s = str(c).strip().upper()
        if s:
            out.append(s)
    return sorted(set(out))


def _select_best_candidate(cusip: str, result: dict) -> dict:
    """
    Choose a conservative mapping candidate.

    Prefer:
      1) Equity market sector
      2) US exchange
      3) Common Stock securityType2

    If multiple equally strong candidates remain, mark ambiguous instead of
    silently choosing one.
    """
    if "error" in result:
        return {
            "CUSIP": cusip,
            "ticker": None,
            "figi": None,
            "name": None,
            "exchCode": None,
            "securityType": None,
            "securityType2": None,
            "mapping_status": "ERROR",
            "mapping_note": str(result.get("error")),
            "candidate_count": 0,
        }

    data = result.get("data") or []
    if not data:
        return {
            "CUSIP": cusip,
            "ticker": None,
            "figi": None,
            "name": None,
            "exchCode": None,
            "securityType": None,
            "securityType2": None,
            "mapping_status": "UNRESOLVED",
            "mapping_note": str(result.get("warning", "No mapping returned")),
            "candidate_count": 0,
        }

    scored = []
    for d in data:
        score = 0
        if d.get("marketSector") == "Equity":
            score += 4
        if d.get("exchCode") == "US":
            score += 3
        if d.get("securityType2") == "Common Stock":
            score += 2
        if d.get("ticker"):
            score += 1
        scored.append((score, d))

    best_score = max(x[0] for x in scored)
    best = [d for score, d in scored if score == best_score]

    # If equally strong candidates disagree on ticker, require review.
    tickers = sorted({d.get("ticker") for d in best if d.get("ticker")})
    ambiguous = len(tickers) > 1

    chosen = best[0]
    return {
        "CUSIP": cusip,
        "ticker": chosen.get("ticker") if not ambiguous else None,
        "figi": chosen.get("figi"),
        "name": chosen.get("name"),
        "exchCode": chosen.get("exchCode"),
        "securityType": chosen.get("securityType"),
        "securityType2": chosen.get("securityType2"),
        "mapping_status": "AMBIGUOUS" if ambiguous else "RESOLVED",
        "mapping_note": (
            f"Multiple equally strong tickers: {tickers}"
            if ambiguous
            else ""
        ),
        "candidate_count": len(data),
    }


def resolve_cusips(
    cusips: Iterable[str],
    api_key: Optional[str] = None,
    sleep_seconds: float = 2.6,
    timeout: int = 60,
) -> pd.DataFrame:
    """
    Resolve CUSIPs through OpenFIGI.

    OpenFIGI currently permits fewer jobs per request without an API key than
    with a key. This function uses conservative batch sizes:
      - 5 jobs/request without key
      - 100 jobs/request with key
    """
    normalized = _normalize_cusips(cusips)
    if not normalized:
        return pd.DataFrame(
            columns=[
                "CUSIP","ticker","figi","name","exchCode","securityType",
                "securityType2","mapping_status","mapping_note","candidate_count"
            ]
        )

    key = api_key or os.environ.get("OPENFIGI_API_KEY")
    batch_size = 100 if key else 5
    headers = _headers(key)

    rows = []
    for start in range(0, len(normalized), batch_size):
        batch = normalized[start:start + batch_size]
        # SEC 13F reports 9-character CUSIPs. OpenFIGI currently accepts
        # the first 8 characters using ID_CUSIP_8_CHR.
        payload = [
            {
                "idType": "ID_CUSIP_8_CHR",
                "idValue": cusip[:8],
                "marketSecDes": "Equity",
            }
            for cusip in batch
        ]

        response = requests.post(
            OPENFIGI_MAPPING_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

        if response.status_code == 429:
            reset = response.headers.get("ratelimit-reset")
            delay = float(reset) if reset and str(reset).replace(".", "", 1).isdigit() else max(sleep_seconds, 3.0)
            time.sleep(delay)
            response = requests.post(
                OPENFIGI_MAPPING_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

        response.raise_for_status()
        results = response.json()

        if not isinstance(results, list) or len(results) != len(batch):
            raise ValueError("OpenFIGI returned an unexpected response shape")

        rows.extend(_select_best_candidate(cusip, result) for cusip, result in zip(batch, results))

        if start + batch_size < len(normalized):
            time.sleep(sleep_seconds if not key else 0.30)

    return pd.DataFrame(rows)


def update_mapping_cache(
    cusips: Iterable[str],
    cache_path: str = "cusip_ticker_mapping.csv",
    api_key: Optional[str] = None,
) -> pd.DataFrame:
    """
    Resolve only missing CUSIPs and merge them into a persistent CSV cache.
    """
    path = Path(cache_path)
    if path.exists():
        cache = pd.read_csv(path, dtype=str)
        if "CUSIP" not in cache.columns:
            raise ValueError(f"{cache_path} is missing CUSIP column")
        cache["CUSIP"] = cache["CUSIP"].astype(str).str.strip().str.upper()
    else:
        cache = pd.DataFrame()

    wanted = _normalize_cusips(cusips)
    existing = set(cache["CUSIP"]) if not cache.empty else set()
    missing = [c for c in wanted if c not in existing]

    if missing:
        fresh = resolve_cusips(missing, api_key=api_key)
        combined = pd.concat([cache, fresh], ignore_index=True, sort=False)
    else:
        combined = cache.copy()

    if not combined.empty:
        combined = (
            combined.sort_values(["CUSIP", "mapping_status"], na_position="last")
            .drop_duplicates(subset=["CUSIP"], keep="last")
            .reset_index(drop=True)
        )
        combined.to_csv(path, index=False)

    return combined


def resolved_only(mapping: pd.DataFrame) -> pd.DataFrame:
    if mapping.empty:
        return mapping.copy()
    return mapping[
        mapping["mapping_status"].eq("RESOLVED")
        & mapping["ticker"].notna()
    ].copy()


if __name__ == "__main__":
    print("OpenFIGI CUSIP resolver loaded.")
    print("Optional: set OPENFIGI_API_KEY for higher throughput.")
