import pandas as pd
import numpy as np

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

# 移除無限大轉為 NaN，CSV 會自動處理成空值
df_out = df_out.replace([np.inf, -np.inf], np.nan)

print("正在匯出 CSV...")
df_out.to_csv('cleaned_unit_prices.csv', index=False, encoding='utf-8')
print("✅ 已成功匯出乾淨的資料表：cleaned_unit_prices.csv")
