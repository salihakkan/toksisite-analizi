import streamlit as st
import pandas as pd

# --- SAYFA AYARLARI ---
st.set_page_config(
    page_title="In Silico Toksisite Analiz Sistemi",
    page_icon="💊",
    layout="centered"
)

# --- ÖZEL CSS (Modern Görünüm İçin) ---
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3em;
        background-color: #007bff;
        color: white;
        font-weight: bold;
    }
    .report-container {
        padding: 20px;
        border-radius: 15px;
        border: 1px solid #dee2e6;
        background-color: white;
    }
    </style>
    """, unsafe_allow_html=True)

# --- VERİ YÜKLEME ---
@st.cache_data
def load_data():
    try:
        # Dosya adı senin iPad'den yüklediğin asıl formata uyarlandı
        df = pd.read_csv('evren_format1_105_satir.csv')
        return df
    except FileNotFoundError:
        st.error("❌ 'evren_format1_105_satir.csv' dosyası bulunamadı! Lütfen dosya yolunu kontrol edin.")
        return None

df = load_data()

if df is not None:
    # --- BAŞLIK VE GİRİŞ ---
    st.title("🧪 In Silico Toksisite Risk Analizi")
    st.markdown("#### TÜBİTAK 2209-A Projesi | Eczacılık Araştırma Platformu")
    st.divider()

    # --- SEÇİM PANELİ ---
    with st.container():
        col1, col2 = st.columns(2)
        
        with col1:
            steroids = sorted(df['Steroid_Adi'].unique())
            selected_steroid = st.selectbox("Steroid Seçiniz", options=steroids)
            
        with col2:
            drugs = sorted(df['Ek_Ilac_Adi'].unique())
            selected_drug = st.selectbox("Ek İlaç Seçiniz", options=drugs)
        
        analyze_btn = st.button("🔍 Risk Analizini Getir")

    st.divider()

    # --- ANALİZ SONUÇLARI ---
    if analyze_btn:
        # Filtreleme işlemi (Exact Match / Tam eşleşme)
        result = df[(df['Steroid_Adi'] == selected_steroid) & 
                    (df['Ek_Ilac_Adi'] == selected_drug)]

        if not result.empty:
            row = result.iloc[0]
            
            st.subheader(f"📋 Analiz Raporu: {selected_steroid} + {selected_drug}")
            
            # Senaryo Bilgisi
            st.caption(f"**Uygulanan Doz Senaryosu:** {row['Doz_Senaryosu']}")

            # Dinamik Renklendirme Mantığı
            risk_class = row['Etiket_Sinerjistik_Risk_Sinifi']
            
            # Risk Sınıfına Göre Kutucuk Belirleme
            if "Yüksek" in risk_class or "Kritik" in risk_class:
                st.error(f"⚠️ **Genel Risk Sınıfı:** {risk_class}")
            elif "Orta" in risk_class:
                st.warning(f"⚠️ **Genel Risk Sınıfı:** {risk_class}")
            else:
                st.success(f"✅ **Genel Risk Sınıfı:** {risk_class}")

            # Detaylı Parametreler (Yan yana kolonlarda)
            detay_col1, detay_col2 = st.columns(2)
            
            with detay_col1:
                st.info(f"🧬 **SwissADME CYP Inhibisyonu**\n\n{row['Steroid_swissadme_cyp_inh']}")
                
            with detay_col2:
                st.info(f"🛡️ **ProTox-III Hepatotoksisite**\n\n{row['Ek_ilac_protox3_ht_durumu']}")

            st.markdown("---")
            st.caption("💡 Not: Bu analiz in silico yöntemlerle elde edilen öngörüleri içerir. Klinik doğrulanma gerektirir.")

        else:
            st.error("❌ Seçilen ilaç kombinasyonuna dair veri tabanında kayıt bulunamamıştır.")

else:
    st.info("Lütfen veri setinin doğru isimlendirildiğinden emin olun.")
