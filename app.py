import streamlit as st
import pandas as pd
import requests
import re
import time
from datetime import datetime
import xml.etree.ElementTree as ET
from google import genai

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
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3em;
        background-color: #007bff;
        color: white;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# --- VERİ YÜKLEME ---
@st.cache_data
def load_data():
    try:
        return pd.read_csv('evren_format1_105_satir.csv')
    except FileNotFoundError:
        return None

# --- APA 7 YAZAR FORMATLAMA YARDIMCISI ---
def format_apa_authors(author_elements):
    formatted_authors = []
    raw_last_names = []

    for author in author_elements:
        collective = author.find("CollectiveName")
        if collective is not None and collective.text:
            name = collective.text.strip()
            formatted_authors.append(name)
            raw_last_names.append(name)
            continue

        last_el = author.find("LastName")
        init_el = author.find("Initials")
        if last_el is not None and last_el.text:
            last_name = last_el.text.strip()
            raw_last_names.append(last_name)
            if init_el is not None and init_el.text:
                initials = " ".join([f"{ch}." for ch in init_el.text.strip()])
                formatted_authors.append(f"{last_name}, {initials}")
            else:
                formatted_authors.append(last_name)

    if not formatted_authors:
        return "Yazar Bilinmiyor", "Anonim"

    if len(raw_last_names) == 1:
        in_text_author = raw_last_names[0]
    elif len(raw_last_names) == 2:
        in_text_author = f"{raw_last_names[0]} & {raw_last_names[1]}"
    else:
        in_text_author = f"{raw_last_names[0]} et al."

    if len(formatted_authors) == 1:
        apa_authors = formatted_authors[0]
    elif len(formatted_authors) <= 20:
        apa_authors = ", ".join(formatted_authors[:-1]) + ", & " + formatted_authors[-1]
    else:
        apa_authors = ", ".join(formatted_authors[:19]) + ", ... " + formatted_authors[-1]

    return apa_authors, in_text_author

# --- PUBMED CANLI TARAMA (SON 10 YIL + EN GÜNCELE GÖRE SIRALI + APA 7) ---
def search_pubmed(term1, term2, max_per_query=4, years_back=10):
    base_search = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    base_fetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    current_year = datetime.now().year

    def run_queries(start_yr):
        found_pmids = []
        notes = []
        queries = [
            (f"({term1}[Title/Abstract]) AND ({term2}[Title/Abstract])", "Doğrudan Kombinasyon"),
            (f"({term1}[Title/Abstract]) AND (hepatotoxicity OR liver OR toxicity OR CYP450)", f"{term1} Toksisite"),
            (f"({term2}[Title/Abstract]) AND (hepatotoxicity OR liver OR DILI OR CYP450)", f"{term2} Toksisite")
        ]
        for idx, (q, label) in enumerate(queries):
            if idx > 0 and len(found_pmids) >= 5:
                break
            try:
                params = {
                    "db": "pubmed",
                    "term": q,
                    "retmode": "json",
                    "retmax": max_per_query,
                    "sort": "relevance",
                    "datetype": "pdat",
                    "mindate": f"{start_yr}/01/01",
                    "maxdate": f"{current_year}/12/31",
                    "tool": "InSilicoToxPlatform"
                }
                resp = requests.get(base_search, params=params, timeout=10).json()
                ids = resp.get("esearchresult", {}).get("idlist", [])
                if ids:
                    notes.append(f"{label}: {len(ids)}")
                    for pmid in ids:
                        if pmid not in found_pmids:
                            found_pmids.append(pmid)
            except Exception:
                continue
        return found_pmids, notes

    start_year = current_year - years_back
    pmids, search_notes = run_queries(start_year)
    range_label = f"{start_year}–{current_year}"

    # Son 10 yılda yeterli makale bulunamazsa otomatik olarak son 20 yıla genişlet
    if len(pmids) < 2:
        fallback_start = current_year - 20
        pmids_20, notes_20 = run_queries(fallback_start)
        if len(pmids_20) > len(pmids):
            pmids = pmids_20
            search_notes = notes_20
            range_label = f"{fallback_start}–{current_year} (Son 10 yıl verisi kısıtlı olduğu için genişletildi)"

    if not pmids:
        return [], f"PubMed üzerinde ({range_label}) eşleşen açık makale bulunamadı."

    articles = []
    try:
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(pmids[:7]),
            "retmode": "xml",
            "tool": "InSilicoToxPlatform"
        }
        xml_data = requests.get(base_fetch, params=fetch_params, timeout=12).content
        root = ET.fromstring(xml_data)

        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//MedlineCitation/PMID")
            title_el = article.find(".//ArticleTitle")
            journal_el = article.find(".//Journal/Title")
            vol_el = article.find(".//JournalIssue/Volume")
            issue_el = article.find(".//JournalIssue/Issue")
            pages_el = article.find(".//Pagination/MedlinePgn")
            year_el = article.find(".//JournalIssue/PubDate/Year")
            medline_date_el = article.find(".//JournalIssue/PubDate/MedlineDate")
            doi_el = article.find(".//ArticleIdList/ArticleId[@IdType='doi']")
            abstract_els = article.findall(".//Abstract/AbstractText")
            author_els = article.findall(".//AuthorList/Author")

            pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else "Bilinmiyor"
            pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

            raw_title = "".join(title_el.itertext()).strip() if title_el is not None else "Başlık Mevcut Değil"
            clean_title = raw_title.rstrip(".")

            if year_el is not None and year_el.text:
                year = year_el.text.strip()
            elif medline_date_el is not None and medline_date_el.text:
                match = re.search(r"\d{4}", medline_date_el.text)
                year = match.group(0) if match else "t.y."
            else:
                year = "t.y."

            year_num = int(year) if year.isdigit() else 0

            journal = journal_el.text.strip() if journal_el is not None and journal_el.text else "PubMed Indexed Journal"
            vol = vol_el.text.strip() if vol_el is not None and vol_el.text else ""
            issue = issue_el.text.strip() if issue_el is not None and issue_el.text else ""
            pages = pages_el.text.strip() if pages_el is not None and pages_el.text else ""
            doi = doi_el.text.strip() if doi_el is not None and doi_el.text else ""

            apa_authors, in_text_author = format_apa_authors(author_els)
            in_text_cite = f"({in_text_author}, {year})"

            journal_part = f"*{journal}*"
            if vol and issue:
                journal_part += f", *{vol}*({issue})"
            elif vol:
                journal_part += f", *{vol}*"
            if pages:
                journal_part += f", {pages}"
            journal_part += "."

            if doi:
                doi_url = f"https://doi.org/{doi}"
                link_part = f"[{doi_url}]({doi_url}) | [PubMed'de Aç]({pubmed_url})"
            else:
                link_part = f"[{pubmed_url}]({pubmed_url})"

            apa_reference = f"{apa_authors} ({year}). {clean_title}. {journal_part} {link_part}"
            abstract = " ".join(["".join(el.itertext()) for el in abstract_els]) if abstract_els else "Özet metni mevcut değil."

            articles.append({
                "pmid": pmid,
                "in_text": in_text_cite,
                "apa": apa_reference,
                "title": clean_title,
                "year": year,
                "year_num": year_num,
                "abstract": abstract[:1500],
                "url": pubmed_url
            })
    except Exception as e:
        return [], f"PubMed veri çekme hatası: {str(e)}"

    # En alakalı bulunan makaleleri en güncelden (2026 -> 2016) eskiye sırala
    articles.sort(key=lambda x: x["year_num"], reverse=True)
    summary_note = f"Tarih Aralığı: {range_label} | " + " • ".join(search_notes)
    return articles, summary_note

# --- YAPAY ZEKA ÇIKTISINI BÖLÜMLEME ---
def parse_ai_response(raw_text):
    def extract_tag(tag, text):
        m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    risk_level = extract_tag("RISK_SINIFI", raw_text)
    risk_summary = extract_tag("RISK_OZET", raw_text)
    report = extract_tag("RAPOR", raw_text)
    notes_block = extract_tag("MAKALE_NOTLARI", raw_text)

    article_reasons = {}
    if notes_block:
        for line in notes_block.splitlines():
            line = line.strip().lstrip("-*• ")
            m = re.match(r"(?:PMID\s*[:#-]?\s*)?(\d+)\s*[:\-–—]\s*(.+)", line, re.IGNORECASE)
            if m:
                article_reasons[m.group(1).strip()] = m.group(2).strip()

    if not report:
        report = raw_text

    return {
        "risk_level": risk_level,
        "risk_summary": risk_summary,
        "report": report,
        "article_reasons": article_reasons
    }

# --- GEMINI AI SENTEZ FONKSİYONU (AKILLI YEDEKLEMELİ) ---
def generate_ai_report(substance1, substance2, scenario, articles, in_silico_context=None):
    api_key = st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        return {"ok": False, "error": "⚠️ Streamlit Secrets içinde 'GEMINI_API_KEY' bulunamadı."}

    if articles:
        lit_text = "\n\n".join([
            f"- PMID: {a['pmid']} | Atıf Kodu: {a['in_text']} | Yıl: {a['year']}\n  Başlık: {a['title']}\n  Özet: {a['abstract']}"
            for a in articles
        ])
    else:
        lit_text = "PubMed taramasında doğrudan eşleşen makale özeti bulunamadı."

    silico_block = f"\n**In Silico Veri Seti Bulguları:**\n{in_silico_context}\n" if in_silico_context else ""

    prompt = f"""
Sen uzman bir klinik toksikolog ve farmakologsun. Aşağıdaki iki madde arasındaki olası ilaç-ilaç veya steroid-ilaç etkileşimini ve organ toksisitesi (özellikle hepatotoksisite / DILI) riskini akademik, net ve kanıta dayalı bir Türkçe ile analiz et.

**İncelenen Maddeler:** {substance1} + {substance2}
**Kullanım / Doz Senaryosu:** {scenario}
{silico_block}
**PubMed Canlı Literatür Taraması Sonuçları (En güncelden eskiye):**
{lit_text}

**ÇIKTI FORMATI (Aşağıdaki 4 etiketi KESİNLİKLE eksiksiz kullan):**

[RISK_SINIFI]
Sadece şu dördünden birini yaz: Kritik Risk, Yüksek Risk, Orta Risk veya Düşük Risk (Güvenli Profil)
[/RISK_SINIFI]

[RISK_OZET]
Bu risk sınıfının verilme nedenini tek, çarpıcı ve bilimsel bir cümleyle özetle.
[/RISK_OZET]

[MAKALE_NOTLARI]
Yukarıda verilen her bir PMID için, o makalenin bu analizle ne kadar uyumlu olduğunu ve neden kaynak olarak değerlendirildiğini (veya doğrudan kombinasyon yerine tekil madde verisi sunduğunu) 1 kısa cümleyle alt alta şu formatta yaz:
PMID_NUMARASI: Kısa seçim/uyumluluk nedeni.
[/MAKALE_NOTLARI]

[RAPOR]
Buraya iki ana başlık halinde detaylı analizi yaz:
### 1. Genel Toksikolojik Değerlendirme
Kombinasyonun ve maruziyet senaryosunun (kronik birikim, kümülatif veya idiyosinkratik etkiler) risk profilini özetle.

### 2. Farmakokinetik ve Farmakodinamik Mekanizma
CYP450 enzimleri, kolestaz/safra yolu, oksidatif stres veya taşıyıcı proteinler üzerinden mekanizmaları açıkla. In Silico veriler negatif görünmesine rağmen risk yüksekse bunun bilimsel nedenini (kronik maruziyet, idiyosinkratik DILI vb.) netleştir.

Kurallar:
- Metin içinde yukarıdaki makalelerden bilgi verirken mutlaka verilen APA metin içi atıf kodunu kullan — örneğin: **(Yazar et al., 2024)**.
- Asla listede olmayan bir makale uydurma; doğrudan ikili çalışma yoksa bireysel kanıtlardan çıkarım yaptığını belirt.
- Rapor sonuna ayrıca kaynakça listesi ekleme (sistem otomatik basacaktır).
[/RAPOR]
"""

    try:
        client = genai.Client(api_key=api_key)

        candidate_models = []
        try:
            for m in client.models.list():
                short_name = getattr(m, "name", "").replace("models/", "")
                actions = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
                lower_name = short_name.lower()

                is_gemini = "gemini" in lower_name
                is_excluded = any(x in lower_name for x in [
                    "embedding", "imagen", "veo", "tts", "audio", "image",
                    "aqa", "robotics", "computer-use", "live", "deep-research"
                ])
                supports_gen = (not actions) or ("generateContent" in actions)

                if is_gemini and not is_excluded and supports_gen:
                    candidate_models.append(short_name)
        except Exception:
            candidate_models = ["gemini-3.8-flash"]

        def model_priority(name):
            n = name.lower()
            if "lite" in n and "preview" not in n:
                return 0
            if "lite" in n:
                return 1
            if "flash" in n and "3.8" not in n and "preview" not in n:
                return 2
            if "flash" in n and "3.8" not in n:
                return 3
            if "3.8-flash" in n:
                return 4
            if "flash" in n:
                return 5
            return 6

        candidate_models = sorted(list(dict.fromkeys(candidate_models)), key=model_priority)
        if not candidate_models:
            candidate_models = ["gemini-3.8-flash"]

        last_error = ""
        for model_name in candidate_models[:6]:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                    if response and response.text:
                        parsed = parse_ai_response(response.text)
                        parsed["ok"] = True
                        parsed["model"] = model_name
                        return parsed
                except Exception as e:
                    last_error = f"{model_name}: {str(e)}"
                    err_str = str(e)
                    if "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str:
                        if attempt == 0:
                            time.sleep(2)
                            continue
                    break

        return {
            "ok": False,
            "error": f"❌ Uygun modeller şu an meşgul. Denenenler: {', '.join(candidate_models[:6])}\n\nSon hata: {last_error}"
        }
    except Exception as e:
        return {"ok": False, "error": f"❌ Yapay zeka analizi sırasında bir hata oluştu: {str(e)}"}

# --- RİSK KARTI GÖSTERİM YARDIMCISI ---
def render_risk_banner(risk_level, risk_summary=""):
    if not risk_level:
        return
    text = f"**Yapay Zeka Risk Sınıflandırması:** {risk_level}"
    if risk_summary:
        text += f"\n\n{risk_summary}"

    lower = risk_level.lower()
    if "kritik" in lower or "yüksek" in lower:
        st.error(f"🚨 {text}")
    elif "orta" in lower:
        st.warning(f"⚠️ {text}")
    elif "düşük" in lower or "güvenli" in lower:
        st.success(f"✅ {text}")
    else:
        st.info(f"ℹ️ {text}")

# --- APA 7 KAYNAKÇA + SEÇİM NEDENİ GÖSTERİM YARDIMCISI ---
def render_bibliography(articles, note, article_reasons):
    if not articles:
        return
    st.divider()
    st.markdown(f"### 📖 Kaynakça (APA 7 Formatı — En Güncelden Eskiye)")
    st.caption(note)
    for idx, art in enumerate(articles, 1):
        st.markdown(f"{idx}. {art['apa']}")
        reason = article_reasons.get(art["pmid"])
        if reason:
            st.caption(f"🎯 **Seçim / Uyumluluk Nedeni:** {reason}")

# --- ANA UYGULAMA ARAYÜZÜ ---
st.title("🧪 In Silico & AI Toksisite Risk Analizi")
st.markdown("#### İleri Düzey Farmakolojik Araştırma ve Canlı Literatür Platformu")

df = load_data()

tab1, tab2 = st.tabs(["📊 Veri Seti & AI Literatür Analizi", "🔬 Serbest Kombinasyon Sorgulama (Canlı)"])

# === SEKME 1: MEVCUT CSV VERİ SETİ + AI ===
with tab1:
    if df is not None:
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

        st.divider()

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

            mekanizma = row.get('Kombinasyon_Mekanizmasi', 'Veri Bulunamadı')
            st.info(f"⚙️ **Kombinasyon Mekanizması:** {mekanizma}")

            detay_col1, detay_col2 = st.columns(2)
            with detay_col1:
                swiss = row.get('Ek_Ilac_SwissADME_CYP_Inh', 'Veri Bulunamadı')
                st.info(f"🧬 **Ek İlaç SwissADME CYP Inhibisyonu**\n\n{swiss}")
            with detay_col2:
                protox = row.get('Ek_Ilac_ProTox3_HT_Durumu', 'Veri Bulunamadı')
                st.info(f"🛡️ **Ek İlaç ProTox-III Hepatotoksisite**\n\n{protox}")

            st.divider()
            st.markdown("### 🤖 Yapay Zeka & Canlı PubMed Literatür Sentezi")
            if st.button("📚 PubMed Literatürü Tara & AI Yorumu Oluştur", key="ai_btn_tab1"):
                with st.spinner("Son 10 yılın PubMed literatürü taranıyor ve bilimsel sentez hazırlanıyor..."):
                    articles, note = search_pubmed(selected_steroid, selected_drug)
                    silico_summary = (
                        f"- Etiketlenen Risk Sınıfı: {risk_class}\n"
                        f"- Kombinasyon Mekanizması: {mekanizma}\n"
                        f"- Ek İlaç SwissADME CYP İnhibisyonu: {swiss}\n"
                        f"- Ek İlaç ProTox-III Hepatotoksisite: {protox}"
                    )
                    ai_res = generate_ai_report(
                        selected_steroid, selected_drug, selected_dose, articles, silico_summary
                    )
                    if ai_res["ok"]:
                        st.caption(f"*(Aktif AI Modeli: `{ai_res['model']}`)*")
                        st.markdown(ai_res["report"])
                        render_bibliography(articles, note, ai_res["article_reasons"])
                    else:
                        st.error(ai_res["error"])
        else:
            st.warning("❌ Veri tabanında bu üçlü kombinasyona ait kayıt bulunamadı. Yan sekmeden canlı sorgulama yapabilirsiniz.")
    else:
        st.error("Veri tabanı dosyası (evren_format1_105_satir.csv) yüklenemedi.")

# === SEKME 2: VERİ SETİNDE OLMAYAN MADDELER İÇİN CANLI SORGU ===
with tab2:
    st.markdown("Veri setinizde yer almayan herhangi iki etken maddeyi yazarak doğrudan **PubMed (Son 10 Yıl) + Yapay Zeka** üzerinden anlık ön risk taraması yapabilirsiniz.")
    s_col1, s_col2, s_col3 = st.columns(3)
    with s_col1:
        custom_sub1 = st.text_input("1. Etken Madde (İngilizce önerilir)", placeholder="Örn: Trenbolone")
    with s_col2:
        custom_sub2 = st.text_input("2. Etken Madde (İngilizce önerilir)", placeholder="Örn: Paracetamol")
    with s_col3:
        custom_scenario = st.selectbox(
            "Maruziyet Senaryosu",
            ["Kronik Uzun Süreli Maruziyet", "Supraterapötik Kür Dozu", "Terapötik Düşük Doz", "Akut Yüksek Doz Yüklemesi"]
        )

    if st.button("🚀 Canlı Literatür Tara ve Analiz Et", key="ai_btn_tab2"):
        if custom_sub1.strip() and custom_sub2.strip():
            with st.spinner(f"{custom_sub1} + {custom_sub2} için son 10 yılın PubMed literatürü taranıyor..."):
                articles, note = search_pubmed(custom_sub1.strip(), custom_sub2.strip())
                ai_res = generate_ai_report(
                    custom_sub1.strip(), custom_sub2.strip(), custom_scenario, articles
                )
                if ai_res["ok"]:
                    st.divider()
                    st.subheader(f"📋 Canlı Analiz Raporu: {custom_sub1.strip()} + {custom_sub2.strip()}")
                    st.caption(f"**Seçilen Senaryo:** {custom_scenario} | **Aktif AI Modeli:** `{ai_res['model']}`")

                    # İlk olarak renkli Risk Kartı (Güvenli / Orta / Yüksek / Kritik)
                    render_risk_banner(ai_res["risk_level"], ai_res["risk_summary"])

                    # Ardından detaylı bilimsel rapor
                    st.markdown(ai_res["report"])

                    # En altta en güncelden eskiye APA 7 kaynakça + seçim nedenleri
                    render_bibliography(articles, note, ai_res["article_reasons"])
                else:
                    st.error(ai_res["error"])
        else:
            st.warning("Lütfen her iki etken madde kutusunu da doldurun.")
