"""Hai model gợi ý đơn giản + hybrid.

- Content-based (CB): mỗi quán là một vector TF-IDF ghép từ tên quán, quận và nội dung
  review. Profile của user = trung bình có trọng số các quán đã chấm (trọng số = điểm - 6,
  nên quán bị chấm thấp kéo profile ra xa).
- Collaborative (CF): item-based KNN trên phần dư của baseline (giống KNNBaseline của
  Surprise). r̂(u,i) = μ + b_u + b_i + Σ_j s_ij·(r_uj - b_uj) / (Σ_j |s_ij| + λ), với j là các
  quán user đã chấm nằm trong top-K láng giềng của i.
- Hybrid: min-max chuẩn hoá điểm hai model rồi trộn: α·CB + (1-α)·CF.

Rating mới của user (lưu trong SQLite) được dùng ngay lúc gợi ý. Các tham số đã học
(bias, độ tương đồng giữa quán) chỉ được tính lại khi restart server.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.preprocessing import normalize
from sklearn.feature_extraction.text import TfidfVectorizer

log = logging.getLogger(__name__)

# --- hyper-params ---
REG_ITEM, REG_USER = 10.0, 15.0  # regularization cho baseline
BASELINE_ITERS = 15
KNN_SHRINK = 10.0  # co lại similarity khi ít user chung
KNN_K = 50  # số láng giềng giữ lại cho mỗi quán
KNN_DAMP = 0.03  # cộng vào mẫu số: ít láng giềng/láng giềng yếu -> kéo về baseline (holdout RMSE 1.725 vs 1.768)
LIKE_THRESHOLD = 6.0  # điểm >= ngưỡng: thích (trọng số dương) trong CB
W_NAME, W_DISTRICT, W_REVIEW = 0.55, 0.15, 0.30  # trọng số các khối feature CB
MAX_REVIEW_CHARS = 6000


def clean_name(name: str, address: str) -> str:
    """Bỏ phần chi nhánh/địa chỉ trong tên quán, vd 'Bún Chả Cá Bà Lý - Bà Huyện Thanh Quan'
    -> 'Bún Chả Cá Bà Lý', để CB không gom các quán chỉ vì cùng tên đường."""
    segs = [s.strip() for s in name.split(" - ")]
    addr = address.lower()
    keep = [segs[0]] + [s for s in segs[1:] if s and not s[0].isdigit() and s.lower() not in addr]
    return " ".join(keep)


@dataclass
class Rec:
    idx: int
    score: float
    reason_idx: int | None = None  # quán đã chấm giải thích cho gợi ý
    cb: float | None = None
    cf: float | None = None
    support: bool = True  # CF: có láng giềng hay chỉ dùng baseline


class Recommender:
    def __init__(self, places: pd.DataFrame, reviews: pd.DataFrame, ratings: pd.DataFrame):
        self.places = places
        self.n_items = len(places)
        self.pid2idx = {int(p): i for i, p in enumerate(places["place_id"])}

        t = time.perf_counter()
        self._fit_baseline(ratings)
        self._fit_item_knn(ratings)
        log.info("CF fitted in %.1fs", time.perf_counter() - t)

        t = time.perf_counter()
        self._fit_content(places, reviews)
        log.info("CB fitted in %.1fs (%d features)", time.perf_counter() - t, self.X.shape[1])

        self._fit_popularity(places)

    # ------------------------------------------------------------------ fitting
    def _fit_baseline(self, ratings: pd.DataFrame) -> None:
        u, _ = pd.factorize(ratings["user_id"])
        i = ratings["place_id"].map(self.pid2idx).to_numpy()
        r = ratings["rating"].to_numpy(dtype=float)
        n_users = u.max() + 1

        mu = r.mean()
        bu = np.zeros(n_users)
        bi = np.zeros(self.n_items)
        cnt_i = np.bincount(i, minlength=self.n_items)
        cnt_u = np.bincount(u, minlength=n_users)
        for _ in range(BASELINE_ITERS):
            bi = np.bincount(i, weights=r - mu - bu[u], minlength=self.n_items) / (REG_ITEM + cnt_i)
            bu = np.bincount(u, weights=r - mu - bi[i], minlength=n_users) / (REG_USER + cnt_u)

        self.mu, self.bi = mu, bi
        self.item_rating_count = cnt_i
        self._train = (u, i, r - mu - bu[u] - bi[i], n_users)

    def _fit_item_knn(self, ratings: pd.DataFrame) -> None:
        u, i, res, n_users = self._train
        shape = (n_users, self.n_items)
        R = sp.csr_matrix((res, (u, i)), shape=shape)
        B = sp.csr_matrix((np.ones_like(res), (u, i)), shape=shape)

        norms = np.sqrt(np.asarray(R.multiply(R).sum(axis=0)).ravel())
        inv = np.divide(1.0, norms, out=np.zeros_like(norms), where=norms > 0)
        D = sp.diags(inv)
        cos = (D @ (R.T @ R) @ D).tocsr()  # cosine trên phần dư (≈ pearson-baseline)

        co = (B.T @ B).tocsr()  # số user chấm chung
        co.data = co.data / (co.data + KNN_SHRINK)
        S = cos.multiply(co).tocsr()
        S.setdiag(0)
        S.data[S.data < 0] = 0  # chỉ giữ láng giềng tương đồng dương
        S.eliminate_zeros()

        # giữ top-K láng giềng cho mỗi quán
        rows, cols, vals = [], [], []
        for row in range(self.n_items):
            start, end = S.indptr[row], S.indptr[row + 1]
            if start == end:
                continue
            d, c = S.data[start:end], S.indices[start:end]
            if len(d) > KNN_K:
                top = np.argpartition(-d, KNN_K)[:KNN_K]
                d, c = d[top], c[top]
            rows.append(np.full(len(d), row))
            cols.append(c)
            vals.append(d)
        self.S = sp.csr_matrix(
            (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
            shape=(self.n_items, self.n_items),
        )
        self.S_csc = self.S.tocsc()
        del self._train

    def _fit_content(self, places: pd.DataFrame, reviews: pd.DataFrame) -> None:
        rv = reviews.sort_values("total_likes", ascending=False)
        rv_text = (rv["title"].fillna("") + ". " + rv["text"].fillna("")).groupby(rv["place_id"]).agg(
            lambda s: " ".join(s)[:MAX_REVIEW_CHARS]
        )
        review_docs = places["place_id"].map(rv_text).fillna("").tolist()
        names = [clean_name(n, a) for n, a in zip(places["name"].fillna(""), places["address"].fillna(""))]

        tf_name = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        tf_review = TfidfVectorizer(
            ngram_range=(1, 2), min_df=3, max_df=0.3, sublinear_tf=True, max_features=100_000
        )
        X_name = tf_name.fit_transform(names)
        X_review = tf_review.fit_transform(review_docs)
        X_dist = sp.csr_matrix(pd.get_dummies(places["district"].fillna("?")).to_numpy(dtype=float))

        self.X = normalize(
            sp.hstack([W_NAME * X_name, W_DISTRICT * X_dist, W_REVIEW * X_review]).tocsr()
        )

    def _fit_popularity(self, places: pd.DataFrame, m: float = 20.0) -> None:
        n = places["total_reviews"].fillna(0).to_numpy(dtype=float)
        avg = places["avg_rating"].fillna(0).to_numpy(dtype=float)
        c = avg[n > 0].mean()
        self.popularity = (avg * n + c * m) / (n + m)  # bayesian average

    # ------------------------------------------------------------------ helpers
    def _user_arrays(self, user_ratings: dict[int, float]):
        items = [(self.pid2idx[p], r) for p, r in user_ratings.items() if p in self.pid2idx]
        if not items:
            return np.array([], dtype=int), np.array([])
        J, r = zip(*items)
        return np.array(J), np.array(r, dtype=float)

    def _mask_seen(self, scores: np.ndarray, J: np.ndarray) -> np.ndarray:
        scores = scores.copy()
        scores[J] = -np.inf
        return scores

    # ------------------------------------------------------------------ scoring
    def cb_scores(self, J: np.ndarray, r: np.ndarray):
        """Trả về (score cho mọi quán, ma trận similarity tới các quán đã chấm, trọng số)."""
        w = r - LIKE_THRESHOLD
        if len(J) == 0 or not np.any(w):
            return None, None, None
        sims = (self.X @ self.X[J].T).toarray()  # (n_items, |J|)
        return sims @ w / np.abs(w).sum(), sims, w

    def cf_scores(self, J: np.ndarray, r: np.ndarray):
        """Trả về (rating dự đoán, có láng giềng hay không, phần dư của user)."""
        if len(J) == 0:
            return None, None, None
        bu = (r - self.mu - self.bi[J]).sum() / (REG_USER + len(J))
        res = r - self.mu - bu - self.bi[J]
        Sj = self.S_csc[:, J]
        num = Sj @ res
        den = np.asarray(abs(Sj).sum(axis=1)).ravel()
        dev = num / (den + KNN_DAMP)
        pred = np.clip(self.mu + bu + self.bi + dev, 0, 10)
        return pred, den > 0, res

    # ------------------------------------------------------------------ public
    def recommend(self, user_ratings: dict[int, float], model: str, k: int = 20, alpha: float = 0.5) -> tuple[list[Rec], str]:
        """Trả về (danh sách gợi ý, model thực sự đã dùng)."""
        J, r = self._user_arrays(user_ratings)
        if len(J) == 0:
            return self.popular(k, exclude=J), "popular"

        if model == "cb":
            cb, sims, w = self.cb_scores(J, r)
            if cb is None:
                return self.popular(k, exclude=J), "popular"
            top = self._topk(self._mask_seen(cb, J), k)
            return [Rec(int(i), float(cb[i]), self._cb_reason(sims[i], w, J), cb=float(cb[i])) for i in top], "cb"

        if model == "cf":
            pred, supported, res = self.cf_scores(J, r)
            # ưu tiên quán có láng giềng (thực sự là CF), sau đó mới tới baseline
            ranking = self._mask_seen(pred + np.where(supported, 100.0, 0.0), J)
            top = self._topk(ranking, k)
            return [
                Rec(int(i), float(pred[i]), self._cf_reason(i, J, res) if supported[i] else None,
                    cf=float(pred[i]), support=bool(supported[i]))
                for i in top
            ], "cf"

        # hybrid
        cb, sims, w = self.cb_scores(J, r)
        pred, supported, res = self.cf_scores(J, r)
        cf_n = _minmax(pred, J)
        if cb is None:
            alpha = 0.0
            cb_n = np.zeros_like(cf_n)
        else:
            cb_n = _minmax(cb, J)
        score = alpha * cb_n + (1 - alpha) * cf_n
        top = self._topk(self._mask_seen(score, J), k)
        out = []
        for i in top:
            cb_part = alpha * cb_n[i]
            cf_part = (1 - alpha) * cf_n[i]
            if cb is not None and cb_part >= cf_part:
                reason = self._cb_reason(sims[i], w, J)
            else:
                reason = self._cf_reason(i, J, res) if supported[i] else None
            out.append(Rec(int(i), float(score[i]), reason,
                           cb=float(cb[i]) if cb is not None else None, cf=float(pred[i]),
                           support=bool(supported[i])))
        return out, "hybrid"

    def popular(self, k: int, exclude: np.ndarray | None = None) -> list[Rec]:
        s = self.popularity if exclude is None or len(exclude) == 0 else self._mask_seen(self.popularity, exclude)
        return [Rec(int(i), float(self.popularity[i])) for i in self._topk(s, k)]

    def similar_content(self, idx: int, k: int = 10) -> list[tuple[int, float]]:
        sims = (self.X @ self.X[idx].T).toarray().ravel()
        sims[idx] = -np.inf
        return [(int(i), float(sims[i])) for i in self._topk(sims, k)]

    def similar_cf(self, idx: int, k: int = 10) -> list[tuple[int, float]]:
        row = self.S.getrow(idx)
        order = np.argsort(-row.data)[:k]
        return [(int(row.indices[o]), float(row.data[o])) for o in order]

    # ------------------------------------------------------------------ reasons
    @staticmethod
    def _cb_reason(sims_row: np.ndarray, w: np.ndarray, J: np.ndarray) -> int | None:
        contrib = sims_row * w
        j = int(np.argmax(contrib))
        return int(J[j]) if contrib[j] > 0 else None

    def _cf_reason(self, i: int, J: np.ndarray, res: np.ndarray) -> int | None:
        contrib = self.S_csc[i, J].toarray().ravel() * res
        j = int(np.argmax(contrib))
        return int(J[j]) if contrib[j] > 0 else None

    @staticmethod
    def _topk(scores: np.ndarray, k: int) -> np.ndarray:
        k = min(k, int(np.isfinite(scores).sum()))
        if k <= 0:
            return np.array([], dtype=int)
        top = np.argpartition(-scores, k - 1)[:k]
        return top[np.argsort(-scores[top])]


def _minmax(x: np.ndarray, exclude: np.ndarray) -> np.ndarray:
    mask = np.ones(len(x), dtype=bool)
    mask[exclude] = False
    lo, hi = x[mask].min(), x[mask].max()
    return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)
