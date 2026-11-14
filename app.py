import streamlit as st
import pandas as pd

# --- SAYFA AYARLARI ---
st.set_page_config(
    page_title="In Silico Toksisite Analiz Sistemi",
    page_icon="💊",
    layout="wide" # 3 kutu yan yana sığsın diye genişlettim
)

# --- ÖZEL CSS ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 10px; height: 3em; background-color: #007bff; color: white; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- VERİ YÜKLEME ---
@st.cache_data
def load_data():
    try:
        return pd.read_csv('evren_format1_105_satir.csv')
    except FileNotFoundError:
        return None

df = load_data()

if df is not None:
    # --- BAŞLIK ---
    st.title("🧪 In Silico Toksisite Risk Analizi")
    st.markdown("#### Farmasötik Toksikoloji Araştırma Platformu") # TÜBİTAK yazısı uçtu
    st.divider()

    # --- SEÇİM PANELİ (Artık 3 Kolon) ---
    col1, col2, col3 = st.columns(3)
    
    with col1:
        steroids = sorted(df['Steroid_Adi'].dropna().unique())
        selected_steroid = st.selectbox("Steroid Seçiniz", options=steroids)
        
    with col2:
        drugs = sorted(df['Ek_Ilac_Adi'].dropna().unique())
        selected_drug = st.selectbox("Ek İlaç Seçiniz", options=drugs)

    with col3:
        # İŞTE BURASI: DOZ SENARYOSU SEÇİM KUTUSU
        dosages = sorted(df['Doz_Senaryosu'].dropna().unique())
        selected_dose = st.selectbox("Doz Senaryosu Seçiniz", options=dosages)
        
    analyze_btn = st.button("🔍 Risk Analizini Getir")
    st.divider()

    # --- ANALİZ SONUÇLARI ---
    if analyze_btn:
        # Artık 3 şarta (Steroid + İlaç + Doz) göre tam isabet filtreliyoruz!
        result = df[(df['Steroid_Adi'] == selected_steroid) & 
                    (df['Ek_Ilac_Adi'] == selected_drug) &
                    (df['Doz_Senaryosu'] == selected_dose)]

        if not result.empty:
            row = result.iloc[0]
            
            st.subheader(f"📋 Analiz Raporu: {selected_steroid} + {selected_drug}")
            st.caption(f"**Seçilen Doz Senaryosu:** {selected_dose}")

            risk_class = str(row.get('Etiket_Sinerjistik_Risk_Sinifi', 'Risk Sınıfı Bulunamadı'))
            
            if "Yüksek" in risk_class or "Kritik" in risk_class:
                st.error(f"⚠️ **Genel Risk Sınıfı:** {risk_class}")
            elif "Orta" in risk_class:
                st.warning(f"⚠️ **Genel Risk Sınıfı:** {risk_class}")
            else:
                st.success(f"✅ **Genel Risk Sınıfı:** {risk_class}")

            detay_col1, detay_col2 = st.columns(2)
            
            with detay_col1:
                # DİKKAT: 'Steroid_swissadme_cyp_inh' kısmını az önce düzelttiğin isimle değiştir
                swiss = row.get('Steroid_swissadme_cyp_inh', '⚠️ Veri Çekilemedi')
                st.info(f"🧬 **SwissADME CYP Inhibisyonu**\n\n{swiss}")
                
            with detay_col2:
                # DİKKAT: 'Ek_ilac_protox3_ht_durumu' kısmını az önce düzelttiğin isimle değiştir
                protox = row.get('Ek_ilac_protox3_ht_durumu', '⚠️ Veri Çekilemedi')
                st.info(f"🛡️ **ProTox-III Hepatotoksisite**\n\n{protox}")

        else:
            st.error("❌ Veri tabanında bu üçlü kombinasyona (Steroid + İlaç + Doz) ait bir kayıt bulunamadı.")
else:
    st.error("Veri tabanı dosyası yüklenemedi.")
