import streamlit as st
import pandas as pd

# --- SAYFA AYARLARI ---
st.set_page_config(
    page_title="In Silico Toksisite Analiz Sistemi",
    page_icon="💊",
    layout="wide"
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
    st.markdown("#### Farmasötik Toksikoloji Araştırma Platformu")
    st.divider()

    # --- SEÇİM PANELİ ---
    col1, col2, col3 = st.columns(3)
    
    with col1:
        steroids = sorted(df['Steroid_Adi'].dropna().unique())
        selected_steroid = st.selectbox("Steroid Seçiniz", options=steroids)
        
    with col2:
        drugs = sorted(df['Ek_Ilac_Adi'].dropna().unique())
        selected_drug = st.selectbox("Ek İlaç Seçiniz", options=drugs)

    with col3:
        dosages = sorted(df['Doz_Senaryosu'].dropna().unique())
        selected_dose = st.selectbox("Doz Senaryosu Seçiniz", options=dosages)
        
    analyze_btn = st.button("🔍 Risk Analizini Getir")
    st.divider()

    # --- ANALİZ SONUÇLARI ---
    if analyze_btn:
        result = df[(df['Steroid_Adi'] == selected_steroid) & 
                    (df['Ek_Ilac_Adi'] == selected_drug) &
                    (df['Doz_Senaryosu'] == selected_dose)]

        if not result.empty:
            row = result.iloc[0]
            
            st.subheader(f"📋 Analiz Raporu: {selected_steroid} + {selected_drug}")
            st.caption(f"**Seçilen Doz Senaryosu:** {selected_dose}")

            # Risk Sınıfı
            risk_class = str(row.get('Etiket_Sinerjistik_Risk_Sinifi', 'Risk Sınıfı Bulunamadı'))
            
            if "Yüksek" in risk_class or "Kritik" in risk_class:
                st.error(f"⚠️ **Genel Risk Sınıfı:** {risk_class}")
            elif "Orta" in risk_class:
                st.warning(f"⚠️ **Genel Risk Sınıfı:** {risk_class}")
            else:
                st.success(f"✅ **Genel Risk Sınıfı:** {risk_class}")

            # YENİ EKLENEN: Kombinasyon Mekanizması
            mekanizma = row.get('Kombinasyon_Mekanizmasi', 'Veri Bulunamadı')
            st.info(f"⚙️ **Kombinasyon Mekanizması:** {mekanizma}")

            detay_col1, detay_col2 = st.columns(2)
            
            # BURASI DÜZELTİLDİ: Orijinal Excel Başlıklarına Göre
            with detay_col1:
                swiss = row.get('Ek_Ilac_SwissADME_CYP_Inh', 'Veri Bulunamadı')
                st.info(f"🧬 **Ek İlaç SwissADME CYP Inhibisyonu**\n\n{swiss}")
                
            with detay_col2:
                protox = row.get('Ek_Ilac_ProTox3_HT_Durumu', 'Veri Bulunamadı')
                st.info(f"🛡️ **Ek İlaç ProTox-III Hepatotoksisite**\n\n{protox}")

        else:
            st.error("❌ Veri tabanında bu üçlü kombinasyona ait bir kayıt bulunamadı.")
else:
    st.error("Veri tabanı dosyası yüklenemedi.")
