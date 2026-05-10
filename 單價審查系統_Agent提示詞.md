工作資料夾內已有兩個原始資料檔：
- 合約單價明細.csv（Tab 分隔，65974 筆）
- 案場地區對照表.xlsx

請依照以下規格，逐一產出 init.sql、data_processor.py、
requirements.txt、app.py，並在 Terminal 中執行
data_processor.py 前先確認我的 .env 設定。

# AI 驅動營造工程單價合理性審查系統 — 開發指令

## 角色設定

你是一位資深的**全端資料工程師（Full-stack Data Engineer）**，擅長 Python、Streamlit 與資料庫架構。你的任務是協助我建立一個「個人專用」的雲端網頁系統，用於管理約 **6.6 萬筆**營造工程單價資料，並透過 AI 實現自動化報價合理性分析。

---

## 技術棧

| 層級 | 選用技術 |
|------|----------|
| 前端 / 網頁框架 | Streamlit (Python) |
| 雲端資料庫 | Supabase (PostgreSQL)，需啟用 `pgvector` 擴充功能 |
| AI Embedding | OpenAI `text-embedding-3-small`（1536 維）|
| AI 分析 | OpenAI GPT-4o |
| 部署環境 | Streamlit Community Cloud |

---

## 原始資料說明（重要，請仔細閱讀）

### 主資料檔：`合約單價明細.csv`

- 實際上是 **Tab 分隔（TSV）** 格式，副檔名為 `.csv`，讀取時需指定 `sep='\t'`
- 編碼：UTF-8
- 總筆數：約 **65,974 筆**
- **沒有日期欄位**，本系統不做時序分析

欄位清單如下（共 15 欄）：

| 原始欄位名稱 | 資料型別 | 空值率 | 說明 |
|---|---|---|---|
| `專案代號` | str | 0% | 案件識別碼，如 `AA100`、`CC43` |
| `PROJM_ENAM` | str | 0% | 案件名稱，如 `中部汽車` |
| `分區` | float | **96.1%** | 案內分區（1~8），**不是地理區域**，可忽略 |
| `合約編號` | str | 0% | 合約識別碼，如 `B0032` |
| `名稱` | str | 0% | 合約工程類別，如 `石材工程`、`防水工程` |
| `統編` | str (mixed) | 3.9% | 廠商統一編號，型別不統一，需轉為字串 |
| `廠商名稱` | str | 3.8% | 廠商名稱 |
| `項目編號` | str | 0% | 工項編碼，如 `0D500012` |
| `項目名稱` | str | 0% | 工項描述（主要搜尋欄位），常內嵌規格，如 `電梯廳牆貼石材乾式T=2cm(夢幻莎安娜)` |
| `單位` | str | 0% | 計量單位，含全形/半形混用 |
| `數量` | float | **51.2%** | 空值多因備用單價；正式單價亦有少量空值 |
| `單價` | float | 4.5% | 目標審查欄位；含少量負值及超大值 |
| `金額` | float | 1.9% | 合計金額 |
| `EB_SPECI` | str | **59.5%** | 規格補充說明（如 `W=19cm`、`H=200cm`），或標記 `備用單價` |
| `REMARK_5` | str | 58.9% | 備註（如 `拉門`、`(實作實算)`），或標記 `備用單價` |

### 地區對照表：`案場地區對照表.xlsx`

工作表名稱：`地區對照表`，共 4 個有效欄位：

| 欄位 | 說明 |
|---|---|
| `專案簡稱` | 格式為 `專案代號-案件名稱`，如 `AA100-中部汽車` |
| `記錄筆數` | 可忽略，僅供參考 |
| `地區` | 值為 `北部` / `中部` / `南部` / `待確認` |
| `縣市` | 值如 `台中市`、`桃園市`，部分為空 |

**JOIN 邏輯**：取 `專案簡稱` 中第一個 `-` 前的字串作為鍵值，與主資料的 `專案代號` 進行對應。

---

## 第一階段：資料預處理與雲端資料庫建置

### 1-A 資料清洗腳本（`data_processor.py`）

撰寫 Python 腳本，執行以下步驟：

#### Step 1：讀取主資料

```python
import pandas as pd
df = pd.read_csv('合約單價明細.csv', sep='\t', encoding='utf-8', dtype={'統編': str}, low_memory=False)
```

#### Step 2：合併地區對照表

```python
region_df = pd.read_excel('案場地區對照表.xlsx', sheet_name='地區對照表')
# 從專案簡稱擷取代號（取第一個 '-' 前的字串）
region_df['專案代號'] = region_df['專案簡稱'].str.split('-').str[0]
df = df.merge(region_df[['專案代號', '地區', '縣市']], on='專案代號', how='left')
```

#### Step 3：標記備用單價

```python
df['is_spare_price'] = (
    (df['EB_SPECI'].fillna('') == '備用單價') |
    (df['REMARK_5'].fillna('') == '備用單價')
)
```

#### Step 4：規格欄位清洗（備用單價標記不計入規格）

```python
df['specification'] = df['EB_SPECI'].apply(
    lambda x: None if pd.isna(x) or x == '備用單價' else x
)
```

#### Step 5：單位標準化（全形 → 半形）

```python
unit_map = {'Ｍ': 'M', 'Ｔ': 'T', 'Ｍ２': 'M2', 'Ｍ３': 'M3', '％': '%'}
df['unit_normalized'] = df['單位'].replace(unit_map)
```

#### Step 6：單價異常旗標（不刪除，加旗標）

```python
df['price_flag'] = None
df.loc[df['單價'] < 0, 'price_flag'] = 'negative'
df.loc[df['單價'] > 1_000_000, 'price_flag'] = 'outlier_high'
```

#### Step 7：欄位映射至目標 Schema

```python
df_out = pd.DataFrame({
    'project_code':   df['專案代號'],
    'project_name':   df['PROJM_ENAM'],
    'region':         df['地區'].fillna('待確認'),
    'city':           df['縣市'],
    'contract_no':    df['合約編號'],
    'contract_type':  df['名稱'],
    'vendor_id':      df['統編'],
    'vendor_name':    df['廠商名稱'],
    'item_code':      df['項目編號'],
    'item_name':      df['項目名稱'],
    'specification':  df['specification'],
    'unit':           df['unit_normalized'],
    'quantity':       df['數量'],
    'price':          pd.to_numeric(df['單價'], errors='coerce'),
    'amount':         pd.to_numeric(df['金額'], errors='coerce'),
    'remark':         df['REMARK_5'].replace('備用單價', None),
    'is_spare_price': df['is_spare_price'],
    'price_flag':     df['price_flag'],
})
```

### 1-B 向量化（Embedding）

**Embedding 文本組合策略**：將三個欄位合併，語意最完整：

```
{contract_type} | {item_name} | {specification}
```

範例：`石材工程 | 廁所背牆石材蓋板T=2cm(印度黑) | W=19cm`

- 若 `specification` 為空，則改為：`{contract_type} | {item_name}`
- 使用 OpenAI `text-embedding-3-small` 模型，維度 1536
- **批次處理**：每批 100 筆呼叫一次 API，並在兩批之間加入 `time.sleep(0.5)` 避免觸發速率限制
- 建議在本地完成向量化後，再一次性上傳至 Supabase，而非逐筆寫入

### 1-C Supabase 初始化（`init.sql`）

```sql
-- 啟用 pgvector
CREATE EXTENSION IF NOT EXISTS vector;

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
    embedding        vector(1536),
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 向量索引（HNSW，適合大量資料的近似最近鄰搜尋）
CREATE INDEX ON unit_prices
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 一般查詢索引
CREATE INDEX idx_unit_prices_item_name    ON unit_prices USING gin(to_tsvector('simple', item_name));
CREATE INDEX idx_unit_prices_contract_type ON unit_prices (contract_type);
CREATE INDEX idx_unit_prices_region        ON unit_prices (region);
CREATE INDEX idx_unit_prices_unit          ON unit_prices (unit);
CREATE INDEX idx_unit_prices_is_spare      ON unit_prices (is_spare_price);

-- Row Level Security（僅限本人存取）
ALTER TABLE unit_prices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "開發者自身存取" ON unit_prices
    USING (auth.uid() = '你的 Supabase User UUID');
```

---

## 第二階段：階層式檢索邏輯（`smart_search` 函數）

實作三層退化式檢索，整合進單一函數 `smart_search(query, region=None, unit=None, top_k=10)`：

### 第一層：關鍵字精準比對（SQL Full-text / ILIKE）

```python
results = supabase.table('unit_prices')\
    .select('*')\
    .ilike('item_name', f'%{query}%')\
    .eq('region', region)  # 若有地區篩選\
    .execute()
```

若結果筆數 ≥ 3，直接回傳，**不進入第二層**。

### 第二層：語意相似度搜尋（pgvector）

當第一層結果 < 3 筆時啟動，使用 Supabase RPC 呼叫向量搜尋：

```sql
-- 需在 Supabase 建立此函數
CREATE OR REPLACE FUNCTION match_unit_prices(
    query_embedding vector(1536),
    match_count INT,
    filter_region TEXT DEFAULT NULL
)
RETURNS TABLE (id UUID, item_name TEXT, price NUMERIC, similarity FLOAT)
LANGUAGE SQL STABLE AS $$
    SELECT id, item_name, price,
           1 - (embedding <=> query_embedding) AS similarity
    FROM unit_prices
    WHERE (filter_region IS NULL OR region = filter_region)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;
```

回傳結果需標示「語意相似」來源，讓使用者知道這是近似結果。

### 第三層：外部行情補位（Web Search + GPT-4o）

當前兩層均無法找到 ≥ 1 筆可用資料時啟動：

- 使用 GPT-4o 搭配 web search 工具（或 Tavily API），以下列提示詞查詢：
  ```
  請查詢台灣營造市場「{query}」的近期行情單價，
  參考來源包含：工程會公共工程經費估算程式、各縣市政府單價資料庫、
  台灣區綜合營造業同業公會等。請回傳單位、單價範圍、資料來源與日期。
  ```
- 回傳結果標示「外部行情參考」，並附上來源網址

---

## 第三階段：Streamlit 網頁介面（`app.py`）

### 版面配置

使用 `st.set_page_config(layout="wide")` 寬版佈局，分為左側篩選欄與右側主內容區。

### 篩選欄（`st.sidebar`）

| 篩選項目 | 元件 | 選項來源 |
|---|---|---|
| 關鍵字搜尋 | `st.text_input` | 自由輸入 |
| 地區 | `st.multiselect` | 北部 / 中部 / 南部 / 待確認 |
| 縣市 | `st.multiselect` | 動態依地區選擇更新 |
| 工程類別 | `st.multiselect` | 取自 `contract_type` distinct 值 |
| 單位 | `st.selectbox` | 取自 `unit` distinct 值（含「全部」） |
| 排除備用單價 | `st.checkbox` | 預設 **打勾**（即預設過濾備用單價）|
| 排除單價異常值 | `st.checkbox` | 預設打勾（排除 `price_flag IS NOT NULL`）|

### 主內容區

#### 搜尋結果表格

使用 `st.dataframe` 顯示結果，欄位順序如下：

```
工程類別 | 工項名稱 | 規格 | 單位 | 單價 | 廠商名稱 | 地區/縣市 | 案件代號 | 備用單價 | 異常旗標
```

- 備用單價列以**淡黃色**背景顯示（使用 `st.dataframe` 的 `style` 功能）
- 異常旗標列以**淡紅色**背景顯示

#### 分析面板（`st.expander` 或 Tab）

只在搜尋有結果時顯示，分三個子頁籤（`st.tabs`）：

**Tab 1：價格統計**

針對過濾後的正常單價（非備用、非異常）計算並顯示：
- 平均單價、中位數、最高/最低價（`st.metric` 元件排列）
- 單價分布直方圖（`st.bar_chart` 或 `plotly`）

**Tab 2：廠商比價**

以廠商為維度，顯示同一工項的報價分布表，欄位：
```
廠商名稱 | 統編 | 報價次數 | 平均單價 | 最低價 | 最高價
```
此為核心比價功能，優先開發完整。

**Tab 3：AI 合理性評論**

按下「產生 AI 評論」按鈕後才觸發（非自動執行，節省 API 費用）。

呼叫 GPT-4o，帶入以下結構化提示詞：

```
你是一位資深的台灣營造工程造價顧問。
以下是我正在審查的工項資料：

工項名稱：{item_name}
規格：{specification}
送審單價：{target_price} 元/{unit}

歷史資料統計（內部資料庫）：
- 比對筆數：{count} 筆
- 平均單價：{mean_price} 元
- 中位數單價：{median_price} 元
- 最低/最高：{min_price} ~ {max_price} 元
- 地區分布：{region_distribution}

請依據以上資料，給出：
1. 此單價的合理性評估（偏高/偏低/合理，以百分比說明差距）
2. 影響單價合理性的可能因素（規格差異、地區差異、施工難度等）
3. 建議審查重點（若需進一步確認，應確認哪些細節）

回應以繁體中文書寫，專業但簡潔，不超過 300 字。
```

---

## 第四階段：安全性與配置

### Secrets 管理

使用 Streamlit Secrets（`.streamlit/secrets.toml`）管理所有機敏資訊：

```toml
[openai]
api_key = "sk-..."

[supabase]
url = "https://xxx.supabase.co"
anon_key = "eyJ..."
service_role_key = "eyJ..."
```

程式內以 `st.secrets["openai"]["api_key"]` 存取，**禁止硬寫在程式碼中**。

### 異常處理

以下情境需給出友善提示而非程式崩潰：

| 情境 | 處理方式 |
|---|---|
| Supabase 連線失敗 | `st.error("資料庫連線失敗，請稍後再試")` + `st.stop()` |
| OpenAI API 額度耗盡 | `st.warning("AI 功能暫時無法使用（API 額度不足），僅顯示資料庫查詢結果")` |
| 搜尋無結果 | 提示使用者目前層級，並詢問是否啟動下一層（按鈕確認）|
| 向量化查詢逾時 | `st.spinner` 顯示進度，超過 10 秒給出提示 |

---

## 交付成果

請依序產出以下四個檔案：

### 1. `data_processor.py`

資料清洗與上傳腳本，包含：
- 讀取 TSV 主資料（`sep='\t'`，`dtype={'統編': str}`）
- 合併地區對照表
- 所有清洗步驟（備用單價標記、單位標準化、異常旗標）
- 批次 Embedding 生成（每批 100 筆，含 rate limit 保護）
- 批次上傳至 Supabase（`upsert` 模式，`on_conflict='item_code,project_code'`）
- 執行進度條與錯誤記錄

### 2. `init.sql`

Supabase 資料庫定義，包含：
- `CREATE TABLE unit_prices`（含所有欄位、型別、預設值）
- `match_unit_prices` RPC 函數
- HNSW 向量索引
- Full-text 與一般查詢索引
- RLS Policy

### 3. `app.py`

Streamlit 主程式，包含：
- `smart_search` 三層檢索函數
- 側邊欄篩選元件
- 結果表格（含備用單價樣式）
- 統計分析 / 廠商比價 / AI 評論三個 Tab
- 所有異常處理邏輯
- `@st.cache_data(ttl=600)` 套用於資料庫查詢，避免重複請求

### 4. `requirements.txt`

```
streamlit>=1.35.0
supabase>=2.4.0
openai>=1.30.0
pandas>=2.0.0
openpyxl>=3.1.0
plotly>=5.20.0
python-dotenv>=1.0.0
numpy>=1.26.0
```

---

## 補充說明（實作時注意事項）

1. **TSV 格式**：原始檔副檔名為 `.csv` 但實為 Tab 分隔，所有讀取程式碼必須使用 `sep='\t'`。
2. **備用單價**：共約 2,256 筆，`is_spare_price=True`，資料庫保留不刪除，UI 預設過濾但可取消勾選顯示，顯示時加黃底標記。
3. **負單價**：64 筆，加 `price_flag='negative'` 旗標，不納入統計計算。
4. **超大單價（>100萬）**：567 筆，可能為合理的「式」計包總價，加 `price_flag='outlier_high'` 旗標，UI 預設過濾但可取消。
5. **地區 JOIN**：對照表中有部分案件地區為「待確認」，JOIN 後 `region` 欄位填入 `'待確認'`，不填 `NULL`，以利篩選。
6. **數量空值**：備用單價數量本就為空，其餘空值數量列仍保留，統計分析改以單價為主，不依賴數量。
7. **廠商名稱截斷**：原始資料廠商名稱有截斷現象（如 `明宥開發實`），屬系統導出限制，資料庫照原樣儲存，UI 可 hover tooltip 顯示完整值（若有）。
