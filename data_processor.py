import pandas as pd
import time
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import google.generativeai as genai
from tqdm import tqdm

def main():
    print("載入環境變數...")
    load_dotenv()
    
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
        print("錯誤：缺少環境變數，請確認 .env 設定了 SUPABASE_URL、SUPABASE_KEY、GEMINI_API_KEY。")
        return

    print("初始化連線...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)

    print("Step 1: 讀取主資料...")
    df = pd.read_csv('合約單價明細.csv', sep='\t', encoding='utf-8', dtype={'統編': str}, low_memory=False)

    print("Step 2: 合併地區對照表...")
    region_df = pd.read_excel('案場地區對照表.xlsx', sheet_name='地區對照表')
    region_df['專案代號'] = region_df['專案簡稱'].str.split('-').str[0]
    df = df.merge(region_df[['專案代號', '地區', '縣市']], on='專案代號', how='left')

    print("Step 3: 標記備用單價...")
    df['is_spare_price'] = (
        (df['EB_SPECI'].fillna('') == '備用單價') |
        (df['REMARK_5'].fillna('') == '備用單價')
    )

    print("Step 4: 規格欄位清洗...")
    df['specification'] = df['EB_SPECI'].apply(
        lambda x: None if pd.isna(x) or x == '備用單價' else x
    )

    print("Step 5: 單位標準化...")
    unit_map = {'Ｍ': 'M', 'Ｔ': 'T', 'Ｍ２': 'M2', 'Ｍ３': 'M3', '％': '%'}
    df['unit_normalized'] = df['單位'].replace(unit_map)

    print("Step 6: 單價異常旗標...")
    df['price_flag'] = None
    df.loc[df['單價'] < 0, 'price_flag'] = 'negative'
    df.loc[df['單價'] > 1_000_000, 'price_flag'] = 'outlier_high'

    print("Step 7: 欄位映射至目標 Schema...")
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

    import numpy as np
    df_out = df_out.replace([np.inf, -np.inf], np.nan)
    df_out = df_out.where(pd.notnull(df_out), None)

    print("開始處理 Embedding 並上傳至 Supabase...")
    records = df_out.to_dict(orient='records')
    batch_size = 100
    
    for i in tqdm(range(0, len(records), batch_size)):
        batch = records[i:i+batch_size]
        
        # 1. 產生 Embedding
        texts_to_embed = []
        for record in batch:
            parts = [str(record['contract_type']), str(record['item_name'])]
            if record['specification']:
                parts.append(str(record['specification']))
            texts_to_embed.append(" | ".join(parts))
            
        try:
            # Gemini embedding batch request
            response = genai.embed_content(
                model="models/embedding-001",
                content=texts_to_embed,
                task_type="retrieval_document"
            )
            embeddings = response['embedding']
            for j, emb in enumerate(embeddings):
                batch[j]['embedding'] = emb
        except Exception as e:
            print(f"API 速率限制或連線錯誤：{e}")
            for j in range(len(batch)):
                batch[j]['embedding'] = None
                
        # 2. 上傳至 Supabase
        try:
            supabase.table('unit_prices').upsert(
                batch, 
                on_conflict='item_code,project_code'
            ).execute()
        except Exception as e:
            print(f"\n上傳錯誤 (Batch {i}): {e}")
            
        time.sleep(1) # 增加一點延遲以符合 Gemini 的速率限制
        
    print("資料處理與上傳完成！")

if __name__ == "__main__":
    main()
