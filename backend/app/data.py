"""Load & clean dữ liệu crawl từ Foody."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

_DISTRICT_RE = re.compile(r"^(Quận|Huyện|Q\.)\s*")


def extract_district(address: str | None) -> str | None:
    if not address:
        return None
    for part in address.split(","):
        part = part.strip()
        if _DISTRICT_RE.match(part):
            name = _DISTRICT_RE.sub("", part).replace("Đà Nẵng", "").strip()
            prefix = "Huyện" if part.startswith("Huyện") else "Quận"
            return f"{prefix} {name}"
    return None


def load_places() -> pd.DataFrame:
    df = pd.read_json(DATA_DIR / "places.jsonl", lines=True)
    df = df.drop_duplicates("place_id").reset_index(drop=True)
    df["district"] = df["address"].map(extract_district)
    return df


def load_reviews() -> pd.DataFrame:
    cols = [
        "review_id", "place_id", "user_id", "user_name", "user_level",
        "rating", "title", "text", "created_at", "total_likes", "picture_urls",
    ]
    df = pd.read_json(DATA_DIR / "reviews.jsonl", lines=True)[cols]
    df = df.dropna(subset=["user_id", "place_id", "rating"])
    df["user_id"] = df["user_id"].astype("int64")
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    return df.drop_duplicates("review_id").reset_index(drop=True)


def build_ratings(reviews: pd.DataFrame, valid_place_ids: set[int]) -> pd.DataFrame:
    """Một user có thể review 1 quán nhiều lần -> lấy trung bình."""
    r = reviews[reviews["place_id"].isin(valid_place_ids)]
    return r.groupby(["user_id", "place_id"], as_index=False)["rating"].mean()
