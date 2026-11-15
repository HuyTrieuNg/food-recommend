from __future__ import annotations

import logging
import math
import os
import time
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .data import build_ratings, load_places, load_reviews
from .recommender import Recommender
from .store import NEW_USER_ID_START, Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

MAX_RECS = 200  # chỉ phân trang trong top-200 gợi ý

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).resolve().parents[1] / "demo.db"))


def norm_text(s: str) -> str:
    """Bỏ dấu tiếng Việt để search: 'Bún Chả' -> 'bun cha'."""
    s = s.lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


class State:
    places: pd.DataFrame
    reviews: pd.DataFrame
    place_json: list[dict]
    data_users: pd.DataFrame
    data_ratings: dict[int, dict[int, float]]
    rec: Recommender
    store: Store


S = State()


def load_state() -> None:
    t = time.perf_counter()
    places = load_places()
    reviews = load_reviews()
    ratings = build_ratings(reviews, set(places["place_id"]))
    log.info("Loaded %d places, %d reviews, %d ratings", len(places), len(reviews), len(ratings))

    # ảnh đại diện: ảnh đầu tiên của review nhiều like nhất có ảnh
    with_pic = reviews[reviews["picture_urls"].map(bool)].sort_values("total_likes", ascending=False)
    image = with_pic.groupby("place_id")["picture_urls"].first().map(lambda x: x[0])
    n_ratings = ratings.groupby("place_id").size()

    places["name_norm"] = places["name"].fillna("").map(norm_text) + " " + places["address"].fillna("").map(norm_text)
    places["image"] = places["place_id"].map(image)
    places["n_ratings"] = places["place_id"].map(n_ratings).fillna(0).astype(int)

    S.place_json = [
        {
            "id": int(p.place_id),
            "name": p.name,
            "address": _clean(p.address),
            "district": _clean(p.district),
            "lat": _clean(p.lat),
            "lon": _clean(p.lon),
            "avg_rating": _clean(p.avg_rating),
            "total_reviews": int(p.total_reviews or 0),
            "url": _clean(p.url) or (f"https://www.foody.vn{p.url_path}" if isinstance(p.url_path, str) else None),
            "image": _clean(p.image),
            "n_ratings": int(p.n_ratings),
        }
        for p in places.itertuples()
    ]

    latest = reviews.sort_values("created_at").groupby("user_id").last()
    users = ratings.groupby("user_id").size().rename("n").to_frame()
    users["name"] = latest["user_name"]
    users["level"] = latest["user_level"]
    users = users.reset_index().sort_values("n", ascending=False)
    users["name_norm"] = users["name"].fillna("").map(norm_text)

    S.data_ratings = {
        int(uid): dict(zip(g["place_id"].astype(int), g["rating"].astype(float)))
        for uid, g in ratings.groupby("user_id")
    }
    S.places, S.reviews, S.data_users = places, reviews, users
    S.rec = Recommender(places, reviews, ratings)
    S.store = Store(DB_PATH)
    log.info("Ready in %.1fs", time.perf_counter() - t)


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_state()
    yield


app = FastAPI(title="Food Recommend Demo", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- helpers
def place_by_id(pid: int) -> dict:
    idx = S.rec.pid2idx.get(pid)
    if idx is None:
        raise HTTPException(404, f"Không tìm thấy quán {pid}")
    return S.place_json[idx]


def user_info(uid: int) -> dict:
    if uid >= NEW_USER_ID_START:
        u = S.store.get_user(uid)
        if not u:
            raise HTTPException(404, "User không tồn tại")
        return {"id": uid, "name": u["name"], "level": None, "is_new": True}
    row = S.data_users[S.data_users["user_id"] == uid]
    if row.empty:
        raise HTTPException(404, "User không tồn tại")
    r = row.iloc[0]
    return {"id": uid, "name": r["name"], "level": _clean(r["level"]), "is_new": False}


def user_ratings(uid: int) -> dict[int, float]:
    """Rating từ data crawl + rating nhập trên demo (rating demo ghi đè)."""
    return {**S.data_ratings.get(uid, {}), **S.store.ratings(uid)}


# ---------------------------------------------------------------- users
class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@app.get("/api/users")
def list_users(q: str = "", limit: int = Query(30, le=200), min_ratings: int = 1):
    qn = norm_text(q.strip())
    new = [
        {"id": u["id"], "name": u["name"], "n_ratings": u["n"], "level": None, "is_new": True}
        for u in S.store.users()
        if not qn or qn in norm_text(u["name"])
    ]
    df = S.data_users[S.data_users["n"] >= min_ratings]
    if qn:
        df = df[df["name_norm"].str.contains(qn, regex=False) | (df["user_id"].astype(str) == qn)]
    data = [
        {"id": int(r.user_id), "name": r.name, "n_ratings": int(r.n), "level": _clean(r.level), "is_new": False}
        for r in df.head(limit).itertuples()
    ]
    return (new + data)[:limit]


@app.post("/api/users")
def create_user(body: NewUser):
    u = S.store.create_user(body.name.strip())
    return {**u, "n_ratings": 0, "level": None, "is_new": True}


@app.get("/api/users/{uid}")
def get_user(uid: int):
    return {**user_info(uid), "n_ratings": len(user_ratings(uid))}


@app.get("/api/users/{uid}/ratings")
def get_user_ratings(uid: int):
    user_info(uid)
    demo = S.store.ratings(uid)
    items = [
        {"place": place_by_id(pid), "rating": round(r, 2), "source": "demo" if pid in demo else "data"}
        for pid, r in user_ratings(uid).items()
        if pid in S.rec.pid2idx
    ]
    items.sort(key=lambda x: (x["source"] != "demo", -x["rating"]))
    return items


class RatingIn(BaseModel):
    place_id: int
    rating: float = Field(ge=0, le=10)


@app.post("/api/users/{uid}/ratings")
def rate(uid: int, body: RatingIn):
    user_info(uid)
    place_by_id(body.place_id)
    S.store.set_rating(uid, body.place_id, body.rating)
    return {"ok": True}


@app.delete("/api/users/{uid}/ratings/{place_id}")
def unrate(uid: int, place_id: int):
    if not S.store.delete_rating(uid, place_id):
        raise HTTPException(400, "Chỉ xoá được rating tạo trên demo")
    return {"ok": True}


# ---------------------------------------------------------------- recommend
@app.get("/api/users/{uid}/recommendations")
def recommend(
    uid: int,
    model: Literal["cb", "cf", "hybrid"] = "hybrid",
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
    alpha: float = Query(0.5, ge=0, le=1),
):
    user_info(uid)
    ratings = user_ratings(uid)
    n_rated = sum(pid in S.rec.pid2idx for pid in ratings)
    total = min(MAX_RECS, S.rec.n_items - n_rated)
    offset = min(offset, max(total - 1, 0))
    k = min(offset + limit, total)
    t = time.perf_counter()
    recs, used = S.rec.recommend(ratings, model, k=k, alpha=alpha)
    items = []
    for r in recs[offset:]:
        reason = None
        if r.reason_idx is not None:
            rp = S.place_json[r.reason_idx]
            reason = {"place_id": rp["id"], "name": rp["name"], "rating": round(ratings[rp["id"]], 2)}
        items.append({
            "place": S.place_json[r.idx],
            "score": round(r.score, 4),
            "cb": None if r.cb is None else round(r.cb, 4),
            "cf": None if r.cf is None else round(r.cf, 3),
            "cf_supported": r.support,
            "reason": reason,
        })
    return {"model": used, "n_user_ratings": len(ratings), "total": total, "offset": offset, "took_ms": round((time.perf_counter() - t) * 1000, 1), "items": items}


# ---------------------------------------------------------------- places
@app.get("/api/districts")
def districts():
    return sorted(S.places["district"].dropna().unique().tolist())


@app.get("/api/places")
def list_places(
    q: str = "",
    district: str | None = None,
    sort: Literal["popular", "rating", "reviews"] = "popular",
    offset: int = 0,
    limit: int = Query(24, le=100),
):
    df = S.places
    mask = pd.Series(True, index=df.index)
    if q.strip():
        mask &= df["name_norm"].str.contains(norm_text(q.strip()), regex=False)
    if district:
        mask &= df["district"] == district
    idx = df.index[mask].to_numpy()
    key = {
        "popular": S.rec.popularity[idx],
        "rating": df["avg_rating"].to_numpy()[idx],
        "reviews": df["total_reviews"].to_numpy()[idx],
    }[sort]
    idx = idx[(-key).argsort(kind="stable")]
    return {"total": len(idx), "items": [S.place_json[i] for i in idx[offset: offset + limit]]}


@app.get("/api/places/{pid}")
def get_place(pid: int, n_reviews: int = 20):
    place = place_by_id(pid)
    idx = S.rec.pid2idx[pid]
    rv = S.reviews[S.reviews["place_id"] == pid].sort_values("created_at", ascending=False).head(n_reviews)
    reviews = [
        {
            "id": int(r.review_id),
            "user_id": int(r.user_id),
            "user_name": r.user_name,
            "rating": r.rating,
            "title": r.title,
            "text": r.text,
            "created_at": r.created_at.isoformat() if pd.notna(r.created_at) else None,
            "pictures": list(r.picture_urls)[:4],
        }
        for r in rv.itertuples()
    ]
    return {
        "place": place,
        "reviews": reviews,
        "similar_content": [{"place": S.place_json[i], "score": round(s, 4)} for i, s in S.rec.similar_content(idx)],
        "similar_cf": [{"place": S.place_json[i], "score": round(s, 4)} for i, s in S.rec.similar_cf(idx)],
    }


@app.get("/api/health")
def health():
    return {"ok": True}
