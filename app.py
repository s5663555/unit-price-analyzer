import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
import plotly.express as px

# 1. 頁面配置
st.set_page_config(page_title="單價合理性審查系統", layout="wide")

# 2. 初始化客戶端與環境變數
def init_clients():
    try:
        supabase: Client = create_client(
            st.secrets["supabase"]["url"],
            st.secrets["supabase"]["anon_key"]
        )
        genai.configure(api_key=st.secrets["gemini"]["api_key"])
        return supabase
    except Exception as e:
        st.error(f"初始化連線失敗，請確認 secrets 設定：{e}")
        st.stop()

supabase = init_clients()
gemini_model = genai.GenerativeModel('gemini-2.5-flash')

# ====== 登入機制 ======
if 'user' not in st.session_state:
    st.session_state.user = None

# 若有登入紀錄，還原 Supabase 連線 Session
if st.session_state.user and 'access_token' in st.session_state:
    try:
        supabase.auth.set_session(st.session_state.access_token, st.session_state.refresh_token)
    except Exception:
        st.session_state.user = None

if not st.session_state.user:
    # 隱藏右上角的 Deploy 與選單
    st.markdown(
        """
        <style>
        [data-testid="stHeader"] {display: none;}
        [data-testid="stToolbar"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True
    )
    
    # 使用 columns 把畫面置中縮窄，避免輸入框過長
    _, col2, _ = st.columns([1, 2, 1])
    
    with col2:
        st.title("🔐 單價審查系統")
        st.markdown("### 請先登入")
        with st.form("login_form"):
            email = st.text_input("電子郵件")
            password = st.text_input("密碼", type="password")
            submit = st.form_submit_button("登入", use_container_width=True)
            
            if submit:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    st.session_state.access_token = res.session.access_token
                    st.session_state.refresh_token = res.session.refresh_token
                    st.rerun()
                except Exception as e:
                    st.error("登入失敗，請檢查帳號密碼。")
    st.stop() # 阻擋後續程式碼執行

# 登出按鈕放在側邊欄最上面
with st.sidebar:
    st.write(f"👤 {st.session_state.user.email}")
    if st.button("登出"):
        supabase.auth.sign_out()
        st.session_state.clear()
        st.rerun()
    st.markdown("---")
# ======================

# 3. 搜尋輔助函數
@st.cache_data(ttl=600)
def smart_search(query: str, base_filters: dict, top_k: int = 50):
    query_builder = supabase.table('unit_prices').select('*')
    
    if base_filters.get('exclude_spare'):
        query_builder = query_builder.eq('is_spare_price', False)
    if base_filters.get('exclude_outlier'):
        query_builder = query_builder.is_('price_flag', 'null')
    if base_filters.get('exclude_lot'):
        query_builder = query_builder.neq('unit', '式')
    
    # 第一層：關鍵字精準比對
    if query:
        res1 = query_builder.ilike('item_name', f'%{query}%').execute()
    else:
        res1 = query_builder.limit(100).execute()
        
    data1 = res1.data
    
    if len(data1) >= 3 or not query:
        return data1, "精準比對 (SQL ILIKE)"

    # 第二層：語意相似度搜尋 (pgvector)
    try:
        response = genai.embed_content(
            model="models/gemini-embedding-2",
            content=query,
            task_type="retrieval_query",
            output_dimensionality=768
        )
        query_embedding = response['embedding']
        
        res2 = supabase.rpc('match_unit_prices', {
            'query_embedding': query_embedding,
            'match_count': top_k,
            'filter_region': None
        }).execute()
        
        if res2.data:
            ids = [r['id'] for r in res2.data]
            res_detail = supabase.table('unit_prices').select('*').in_('id', ids).execute()
            
            data2 = res_detail.data
            if base_filters.get('exclude_spare'):
                data2 = [d for d in data2 if not d.get('is_spare_price')]
            if base_filters.get('exclude_outlier'):
                data2 = [d for d in data2 if d.get('price_flag') is None]
            if base_filters.get('exclude_lot'):
                data2 = [d for d in data2 if d.get('unit') != '式']
                
            if len(data2) >= 1:
                return data2, "語意相似度 (pgvector)"
    except Exception as e:
        st.warning(f"語意搜尋失敗：{e}")

    # 第三層：外部行情補位
    return [], "無內部資料"

def get_external_pricing(query: str):
    try:
        prompt = f"""請查詢台灣營造市場「{query}」的近期行情單價，
參考來源包含：工程會公共工程經費估算程式、各縣市政府單價資料庫、台灣區綜合營造業同業公會等。
請回傳單位、單價範圍、資料來源與日期。"""

        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"外部行情查詢失敗：{e}"

def generate_ai_comment(item_name, specification, target_price, unit, df_stats):
    try:
        count = len(df_stats)
        mean_price = df_stats['單價'].mean()
        median_price = df_stats['單價'].median()
        min_price = df_stats['單價'].min()
        max_price = df_stats['單價'].max()
        region_dist = df_stats['地區'].value_counts().to_dict()

        prompt = f"""你是一位資深的台灣營造工程造價顧問。
以下是我正在審查的工項資料：

工項名稱：{item_name}
規格：{specification}
送審單價：{target_price} 元/{unit}

歷史資料統計（內部資料庫）：
- 比對筆數：{count} 筆
- 平均單價：{mean_price:.2f} 元
- 中位數單價：{median_price:.2f} 元
- 最低/最高：{min_price:.2f} ~ {max_price:.2f} 元
- 地區分布：{region_dist}

請依據以上資料，給出：
1. 此單價的合理性評估（偏高/偏低/合理，以百分比說明差距）
2. 影響單價合理性的可能因素（規格差異、地區差異、施工難度等）
3. 建議審查重點（若需進一步確認，應確認哪些細節）

回應以繁體中文書寫，專業但簡潔，不超過 300 字。"""

        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"產生 AI 評論失敗：{e}"

# 4. 側邊欄 UI - 基礎搜尋輸入
with st.sidebar:
    st.header("🔍 關鍵字搜尋")
    search_query = st.text_input("工項名稱/規格", placeholder="例如：石材工程")
    
    st.markdown("---")
    st.subheader("基礎排除條件")
    exclude_spare = st.checkbox("排除備用單價", value=False)
    exclude_outlier = st.checkbox("排除單價異常值", value=True)
    exclude_lot = st.checkbox("排除以「式」計價", value=False)
    
    base_filters = {
        'exclude_spare': exclude_spare,
        'exclude_outlier': exclude_outlier,
        'exclude_lot': exclude_lot
    }

# 5. 主內容區與動態檢索
st.title("🏗️ AI 驅動營造工程單價審查系統")

with st.spinner("檢索中..."):
    base_results, source_layer = smart_search(search_query, base_filters, top_k=50)

df_base = pd.DataFrame(base_results)

# 6. 側邊欄 UI - 動態進階篩選 (只顯示搜尋結果中有出現的選項)
with st.sidebar:
    if not df_base.empty:
        st.markdown("---")
        st.subheader("進階篩選 (基於搜尋結果)")
        
        region_list = sorted([r for r in df_base['region'].unique() if pd.notna(r) and r])
        city_list = sorted([c for c in df_base['city'].unique() if pd.notna(c) and c])
        type_list = sorted([t for t in df_base['contract_type'].unique() if pd.notna(t) and t])
        unit_list = ["全部"] + sorted([u for u in df_base['unit'].unique() if pd.notna(u) and u])
        
        selected_regions = st.multiselect("地區", region_list)
        selected_cities = st.multiselect("縣市", city_list)
        selected_types = st.multiselect("工程類別", type_list)
        selected_unit = st.selectbox("單位", unit_list)
    else:
        selected_regions, selected_cities, selected_types, selected_unit = [], [], [], "全部"

# 套用動態篩選
if not df_base.empty:
    df_res = df_base.copy()
    if selected_regions:
        df_res = df_res[df_res['region'].isin(selected_regions)]
    if selected_cities:
        df_res = df_res[df_res['city'].isin(selected_cities)]
    if selected_types:
        df_res = df_res[df_res['contract_type'].isin(selected_types)]
    if selected_unit and selected_unit != "全部":
        df_res = df_res[df_res['unit'] == selected_unit]
else:
    df_res = pd.DataFrame()

if df_res.empty:
    if source_layer == "無內部資料" and search_query:
        st.warning("內部資料庫無相符結果。是否呼叫 AI 查詢外部行情？")
        if st.button("查詢外部行情"):
            with st.spinner("呼叫 Gemini 查詢中..."):
                ext_result = get_external_pricing(search_query)
                st.info("🌐 外部行情參考")
                st.markdown(ext_result)
    else:
        st.info("無符合條件的資料。")
else:
    st.success(f"找到 {len(df_res)} 筆資料（來源：{source_layer}）")
    
    # 這裡不要再宣告 df_res = pd.DataFrame(results)，沿用前面 Pandas 篩選過後的 df_res
    
    display_cols = {
        'contract_type': '工程類別',
        'item_name': '工項名稱',
        'specification': '規格',
        'unit': '單位',
        'price': '單價',
        'vendor_name': '廠商名稱',
        'vendor_id': '統編',
        'region': '地區',
        'city': '縣市',
        'project_name': '案件簡稱',
        'is_spare_price': '備用單價',
        'price_flag': '異常旗標'
    }
    
    df_display = df_res[list(display_cols.keys())].rename(columns=display_cols)
    df_display['地區/縣市'] = df_display['地區'].fillna('') + '/' + df_display['縣市'].fillna('')
    
    final_cols = ['工程類別', '工項名稱', '規格', '單位', '單價', '廠商名稱', '地區/縣市', '案件簡稱', '備用單價', '異常旗標']
    df_final = df_display[final_cols]
    
    def highlight_rows(row):
        styles = [''] * len(row)
        if row['備用單價']:
            styles = ['background-color: #fff3cd; color: #856404'] * len(row)
        elif pd.notna(row['異常旗標']):
            styles = ['background-color: #f8d7da; color: #721c24'] * len(row)
        return styles

    st.dataframe(
        df_final.style.apply(highlight_rows, axis=1).format({'單價': '{:,.2f}'}),
        use_container_width=True,
        hide_index=True
    )

    st.markdown("### 📊 分析面板")
    
    df_stats = df_display[(~df_display['備用單價']) & (df_display['異常旗標'].isna())]
    
    if df_stats.empty:
        st.warning("沒有可供分析的正常單價資料。")
    else:
        tab1, tab2, tab3 = st.tabs(["價格統計", "廠商比價", "AI 合理性評論"])
        
        with tab1:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("平均單價", f"{df_stats['單價'].mean():,.2f}")
            col2.metric("中位數", f"{df_stats['單價'].median():,.2f}")
            col3.metric("最低價", f"{df_stats['單價'].min():,.2f}")
            col4.metric("最高價", f"{df_stats['單價'].max():,.2f}")
            
            fig = px.histogram(df_stats, x="單價", nbins=20, title="單價分布直方圖")
            st.plotly_chart(fig, use_container_width=True)
            
        with tab2:
            st.markdown("#### 廠商報價分布表")
            vendor_stats = df_stats.groupby(['廠商名稱', '統編']).agg(
                報價次數=('單價', 'count'),
                平均單價=('單價', 'mean'),
                最低價=('單價', 'min'),
                最高價=('單價', 'max')
            ).reset_index()
            
            vendor_stats['平均單價'] = vendor_stats['平均單價'].round(2)
            st.dataframe(vendor_stats, use_container_width=True, hide_index=True)
            
        with tab3:
            st.markdown("#### AI 單價合理性評論")
            st.info("請輸入送審單價與規格，以產生 AI 評論")
            
            default_item = search_query if search_query else df_stats.iloc[0]['工項名稱']
            default_spec = df_stats.iloc[0]['規格'] if pd.notna(df_stats.iloc[0]['規格']) else ""
            default_unit = df_stats.iloc[0]['單位']
            
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                target_item = st.text_input("工項名稱", value=default_item)
            with col_b:
                target_spec = st.text_input("規格", value=default_spec)
            with col_c:
                target_unit = st.text_input("單位", value=default_unit)
                
            target_price = st.number_input("送審單價", value=float(df_stats['單價'].median()), min_value=0.0)
            
            if st.button("產生 AI 評論"):
                with st.spinner("Gemini 分析中..."):
                    comment = generate_ai_comment(
                        target_item, target_spec, target_price, target_unit, df_stats
                    )
                    st.success("分析完成")
                    st.markdown(f"> {comment}")
