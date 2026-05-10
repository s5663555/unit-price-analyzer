-- 建立 extensions schema (Supabase 建議將擴充套件放在這裡)
CREATE SCHEMA IF NOT EXISTS extensions;

-- 啟用 pgvector
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- 主資料表
CREATE TABLE unit_prices (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code     TEXT NOT NULL,
    project_name     TEXT,
    region           TEXT DEFAULT '待確認',
    city             TEXT,
    contract_no      TEXT,
    contract_type    TEXT,
    vendor_id        TEXT,
    vendor_name      TEXT,
    item_code        TEXT,
    item_name        TEXT NOT NULL,
    specification    TEXT,
    unit             TEXT,
    quantity         NUMERIC,
    price            NUMERIC,
    amount           NUMERIC,
    remark           TEXT,
    is_spare_price   BOOLEAN DEFAULT FALSE,
    price_flag       TEXT,          -- 'negative' | 'outlier_high' | NULL
    embedding        extensions.vector(768),
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 向量索引（HNSW，適合大量資料的近似最近鄰搜尋）
-- 注意：HNSW 索引非常佔用空間（約 200MB+）。在 Supabase 免費版 (上限 500MB) 中，
-- 如果資料量在 10 萬筆以下，建議保持註解，使用內建的精確比對（Exact Search）即可，速度依然很快。
-- CREATE INDEX ON unit_prices
--     USING hnsw (embedding vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64);

-- 一般查詢索引
CREATE INDEX idx_unit_prices_item_name    ON unit_prices USING gin(to_tsvector('simple', item_name));
CREATE INDEX idx_unit_prices_contract_type ON unit_prices (contract_type);
CREATE INDEX idx_unit_prices_region        ON unit_prices (region);
CREATE INDEX idx_unit_prices_unit          ON unit_prices (unit);
CREATE INDEX idx_unit_prices_is_spare      ON unit_prices (is_spare_price);

-- Row Level Security（因為目前 Streamlit 沒有實作登入，先註解掉，避免讀不到資料）
-- ALTER TABLE unit_prices ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "開發者自身存取" ON unit_prices
--     USING (auth.uid() = '你的 Supabase User UUID');
