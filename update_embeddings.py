import time
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import google.generativeai as genai
from tqdm import tqdm

def main():
    print("載入設定與初始化連線...")
    load_dotenv()
    
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)

    print("正在查詢需要產生 Embedding 的資料筆數...")
    # 計算 embedding 是 null 的資料筆數
    res = supabase.table('unit_prices').select('id', count='exact').is_('embedding', 'null').execute()
    total_count = res.count
    
    if total_count == 0:
        print("🎉 所有資料都已經有 Embedding 了！")
        return
        
    print(f"共有 {total_count} 筆資料尚未擁有 Embedding 向量。")
    print("開始逐批呼叫 Gemini API 並更新至資料庫 (支援隨時中斷，下次執行會自動接續)...\n")
    
    batch_size = 100
    pbar = tqdm(total=total_count)
    
    while True:
        # 每次抓取 100 筆沒有 embedding 的資料
        # 改為 select('*') 取得完整欄位，避免 upsert 時違反 not-null 限制
        res = supabase.table('unit_prices').select('*')\
            .is_('embedding', 'null')\
            .limit(batch_size)\
            .execute()
            
        records = res.data
        if not records:
            break
            
        texts_to_embed = []
        for record in records:
            parts = [str(record['contract_type'] or ''), str(record['item_name'] or '')]
            if record['specification']:
                parts.append(str(record['specification']))
            texts_to_embed.append(" | ".join(parts))
            
        try:
            # 產生 Embeddings
            response = genai.embed_content(
                model="models/gemini-embedding-2",
                content=texts_to_embed,
                task_type="retrieval_document",
                output_dimensionality=768
            )
            embeddings = response['embedding']
            
            # 包含所有原始資料，加上新的 embedding 一起 upsert
            updates = []
            for i, record in enumerate(records):
                record['embedding'] = embeddings[i]
                updates.append(record)
                
            supabase.table('unit_prices').upsert(updates).execute()
            
            pbar.update(len(records))
            time.sleep(1) # 停頓 1 秒，避免觸發 Gemini API 速率限制
            
        except Exception as e:
            print(f"\n處理發生錯誤 (可能遭遇速率限制)：{e}")
            print("暫停 5 秒後重試...")
            time.sleep(5)

if __name__ == "__main__":
    main()
