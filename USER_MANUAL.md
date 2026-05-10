# 🏗️ AI 驅動營造工程單價審查系統 - 使用者說明書

本系統旨在協助工程估算與發包人員，透過歷史大數據與 AI 語意檢索技術，快速審查並評估工程單價的合理性。

---

## 🏛️ 系統架構與介面關聯

本系統由四個主要雲端與開源服務緊密結合而成：

1. **GitHub (版本控制中心)**：負責儲存系統的所有程式碼（包含 `app.py`、`.gitignore` 等）。它也是連接 Streamlit 的橋樑，確保你每次修改程式碼都能被雲端接收。
2. **Streamlit Community Cloud (網頁部屬與前端介面)**：這就是你與同事實際使用的 Web 介面。它會自動從 GitHub 拉取最新的程式碼並建立成網站。
3. **Supabase (資料庫與身分驗證)**：
   - **PostgreSQL + pgvector**：儲存所有合約單價歷史紀錄，以及供 AI 檢索的「語意向量 (Embeddings)」。
   - **Authentication & RLS**：管理能登入這個網頁的帳號，並從資料庫底層鎖住資料（Row Level Security），確保沒有帳號的人絕對無法查詢。
4. **Google Gemini API (AI 大腦)**：負責在背後把使用者的關鍵字轉成向量，以及自動生成專業的「單價合理性顧問評論」。

---

## 🌟 核心特色與運作邏輯

本系統的搜尋引擎採用 **「三層式智慧檢索架構」**，確保無論你輸入什麼關鍵字，都能找到最相關的參考單價：

1. **第一層：精準關鍵字比對 (SQL ILIKE)**
   優先在資料庫中尋找完全包含該關鍵字的工項。如果找到足夠多的資料，就會直接回傳，確保精準度最高。
2. **第二層：AI 語意相似度檢索 (pgvector)**
   若查無完全相符的資料（例如：輸入「石材」，但資料庫只有「大理石」），系統會自動透過 Gemini 轉換為向量，並尋找「概念最相近」的工項。
3. **第三層：AI 外部市場行情補位 (LLM)**
   如果連語意檢索都找不到資料，系統會詢問你是否呼叫 AI 查詢外部公開市場資料（如工程會、各縣市政府單價），提供市場行情參考。

---

## 💻 網頁介面功能與操作步驟

### 1. 🔍 動態篩選區 (左側邊欄)
* **關鍵字搜尋**：輸入「工項名稱」或「規格」（例如：`15cm RC牆`）。
* **進階動態篩選**：系統會**自動根據你的搜尋結果**，動態產生對應的「地區/縣市/工程類別/單位」選單，避免出現與搜尋無關的選項干擾。
* **進階排除設定**：可自由排除「備用單價」或「單價異常值」。

### 2. 📋 檢索結果明細表 (主畫面)
符合條件的歷史單價將會以表格呈現，單價已自動處理千分位並保留兩位小數。
* 🟡 **黃色底色**：備用單價。
* 🔴 **紅色底色**：異常旗標 (異常值)。

### 3. 📊 分析面板 (資料視覺化)
* **價格統計**：顯示平均單價、中位數、最低/高價，與單價常態分佈圖。
* **廠商比價**：自動彙整相同廠商的報價次數與歷史行情。
* **AI 合理性評論**：輸入你的**「送審單價」**，AI 會結合歷史大數據，評估該單價是否合理、受什麼因素影響，並給出議價建議。

---

## ☁️ 系統部屬教學 (Deploy)

如果你在電腦上修改了程式碼，想把更新發布到網路上，請遵循以下步驟：

1. **將程式碼推上 GitHub** (在本地終端機執行)：
   ```bash
   git add .
   git commit -m "你的更新說明"
   git push origin main
   ```
2. **Streamlit 自動部屬**：
   - 只要你把程式碼推上 GitHub 的 `main` 分支，Streamlit Community Cloud 就會**自動偵測並重新載入**你的網頁。
   - *(若是初次建立，請至 [share.streamlit.io](https://share.streamlit.io/) 點選 New App，並連結你的 GitHub Repo。)*
3. **設定機密 (Secrets)**：
   - 在 Streamlit Cloud 後台的 App Settings -> Secrets 中，必須填入與本地 `.streamlit/secrets.toml` 相同的內容，系統才連得上 Supabase 與 Gemini。

---

## 👥 帳號管理與權限分享

本系統已預設啟用 Supabase Authentication 與 RLS 資料庫門禁。如果要開通權限給同事：

1. **建立帳號**：進入 Supabase 後台 -> **Authentication** -> Add User，輸入同事的 Email 與密碼。
2. **發放網址**：將 Streamlit 網址與帳密交給同事。
3. **確認 RLS 權限開放**：
   為確保所有已建立帳號的員工都能查詢，請在 Supabase 的 **SQL Editor** 執行過以下語法（只需設定一次）：
   ```sql
   -- 允許所有「已登入」的使用者查詢單價表
   DROP POLICY IF EXISTS "開發者自身存取" ON unit_prices;
   CREATE POLICY "內部員工皆可存取" ON unit_prices
       FOR SELECT 
       TO authenticated
       USING (true);
   ```

---

## ⚙️ 系統維護與資料更新說明 (Data Pipeline)

當你有新合約的單價資料要匯入時，必須讓 AI 重新學習並產生 Embedding 向量：

1. 將新的工程資料整理成 CSV，匯入 Supabase 的 `unit_prices` 資料表。
2. 開啟終端機，執行以下腳本：
   ```bash
   python update_embeddings.py
   ```
3. 腳本會自動掃描「還沒有產生語意向量」的新資料，並透過 Gemini 批次更新寫入。
4. **效能提示**：若單次更新超過數萬筆，建議先在 Supabase SQL Editor 執行 `DROP INDEX IF EXISTS unit_prices_embedding_idx;` 刪除索引。等 Python 腳本跑完後，再重新執行 `CREATE INDEX ON unit_prices USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);` 重建索引，避免 Timeout 錯誤。
