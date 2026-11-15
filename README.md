# Food Recommend Demo

Web demo hệ thống gợi ý quán ăn Đà Nẵng, dùng data crawl từ Foody (`data/`).
Backend viết bằng FastAPI, frontend dùng React + Vite + Mantine.

## Chạy

```bash
# Backend (cổng 8000). Lúc khởi động mất khoảng 10s để load data và fit model.
cd backend
uv sync
uv run uvicorn app.main:app --port 8000 --reload

# Frontend (cổng 5173). /api được proxy sang backend.
cd frontend
npm install
npm run dev
```

Mở http://localhost:5173. API docs ở http://localhost:8000/docs.

## Tính năng

- **User**: chọn user có sẵn trong data (sắp theo số rating) hoặc tạo user mới. Rating nhập trên demo được lưu ở `backend/demo.db` (SQLite) và đè lên rating từ data.
- **Gợi ý**: có 3 tab Content-based / Collaborative / Hybrid (slider α), kèm giải thích dạng "Vì bạn đã chấm X".
- **Khám phá**: tìm quán (không cần gõ dấu), lọc theo quận, sắp xếp, chấm điểm (5 sao × 2 = thang 10).
- **Chi tiết quán**: xem review, quán tương tự theo nội dung và theo CF.

## Model (`backend/app/recommender.py`)

| Model | Cách làm |
|---|---|
| Content-based | Ghép TF-IDF của tên quán (đã bỏ phần tên đường/chi nhánh) với one-hot quận và TF-IDF nội dung review. Profile user = Σ (rating − 6)·vector quán. Điểm của một quán = cosine với profile. |
| Collaborative | Item-based KNN trên phần dư của baseline `μ + b_u + b_i` (giống KNNBaseline). Similarity là cosine có shrinkage, giữ top-50 láng giềng. Có damping ở mẫu số. Quán không có láng giềng thì dùng baseline. |
| Hybrid | `α·minmax(CB) + (1−α)·minmax(CF)` |
| Cold-start | User chưa có rating thì gợi ý theo Bayesian average của `avg_rating` trên Foody. |

Đánh giá nhanh trên holdout (giữ lại 1 rating/user với user có ≥3 rating): RMSE của CF là 1.725, của baseline là 1.768.

Rating mới được dùng ngay khi gợi ý. Tham số đã học (bias, similarity) chỉ tính lại khi restart backend.

Muốn thay bằng model đã train: implement lại `Recommender.recommend()` hoặc thêm model mới vào endpoint
`GET /api/users/{id}/recommendations?model=...`.
