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

# --- YAYGIN TÜRKÇE -> İNGİLİZCE FARMAKOLOJİK SÖZLÜK (HIZLI ÖNBELLEK) ---
PHARMA_TR_EN = {
    "boldenon": "Boldenone",
    "testosteron": "Testosterone",
    "testosteron enantat": "Testosterone enanthate",
    "testosteron propionat": "Testosterone propionate",
    "testosteron sipionat": "Testosterone cypionate",
    "nandrolon": "Nandrolone",
    "nandrolon dekanoat": "Nandrolone decanoate",
    "trenbolon": "Trenbolone",
    "trenbolon asetat": "Trenbolone acetate",
    "stanozolol": "Stanozolol",
    "oksandrolon": "Oxandrolone",
    "oksimetolon": "Oxymetholone",
    "metandrostenolon": "Methandrostenolone",
    "metandienon": "Metandienone",
    "drostanolon": "Drostanolone",
    "metenolon": "Metenolone",
    "parasetamol": "Paracetamol",
    "asetaminofen": "Acetaminophen",
    "amoksisilin klavulanik asit": "Amoxicillin clavulanic acid",
    "amoksisilin/klavulanik asit": "Amoxicillin clavulanic acid",
    "amoksisilin": "Amoxicillin",
    "torasemid": "Torasemide",
    "furosemid": "Furosemide",
    "ibuprofen": "Ibuprofen",
    "diklofenak": "Diclofenac",
    "naproksen": "Naproxen",
    "izotretinoin": "Isotretinoin",
    "atorvastatin": "Atorvastatin",
    "rosuvastatin": "Rosuvastatin",
    "simvastatin": "Simvastatin",
    "metformin": "Metformin",
    "fluoksetin": "Fluoxetine",
    "sertralin": "Sertraline",
    "ketokonazol": "Ketoconazole",
    "flukonazol": "Fluconazole",
    "azitromisin": "Azithromycin",
    "klaritromisin": "Clarithromycin",
    "siprofloksasin": "Ciprofloxacin",
    "tamoksifen": "Tamoxifen",
    "klomifen": "Clomiphene",
    "anastrozol": "Anastrozole",
    "letrozol": "Letrozole",
    "spironolakton": "Spironolactone",
    "etanol": "Ethanol",
    "alkol": "Alcohol",
    "kafein": "Caffeine",
}

# --- VERİ YÜKLEME ---
@st.cache_data
def load_data():
    try:
        return pd.read_csv('evren_format1_105_satir.csv')
    except FileNotFoundError:
        return None

# --- MODEL ÖNCELİK SIRALAMASI (EN GÜÇLÜDEN HAFİFE) ---
def model_strength_priority(name):
    n = name.lower()
    if any(x in n for x in ["argon", "carbon", "pro"]) and "preview" not in n:
        return 0
    if "hydrogen" in n and "lite" not in n:
        return 1
    if any(x in n for x in ["argon", "carbon", "pro"]):
        return 2
    if "flash" in n and "lite" not in n and "preview" not in n:
        return 3
    if "flash" in n and "lite" not in n:
        return 4
    if "lite" in n and "preview" not in n:
        return 5
    if "lite" in n:
        return 6
    return 7

# --- API'YE AÇIK MODELLERİ CANLI LİSTELE (10 DK ÖNBELLEKLİ) ---
@st.cache_data(ttl=600, show_spinner=False)
def get_available_models():
    api_key = st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        return []
    try:
        client = genai.Client(api_key=api_key)
        models = []
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
                models.append(short_name)

        models = sorted(list(dict.fromkeys(models)), key=model_strength_priority)
        return models
    except Exception:
        return ["gemini-3.8-flash"]

# --- OTOMATİK TÜRKÇE -> İNGİLİZCE FARMAKOLOJİK AD ÇEVİRİSİ ---
@st.cache_data(ttl=3600, show_spinner=False)
def translate_drug_for_pubmed(term, available_models):
    clean = term.strip()
    if not clean:
        return clean

    # Parantez içi açıklamalar varsa ayırıp temel madde adını temizle
    base_clean = re.sub(r"\s*\(.*?\)\s*", " ", clean).strip()
    key = re.sub(r"\s+", " ", base_clean.lower())
    if key in PHARMA_TR_EN:
        return PHARMA_TR_EN[key]

    api_key = st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        return base_clean

    # Çeviri işlemi için en hızlı çalışan modeli öne al
    fast_models = sorted(
        available_models if available_models else ["gemini-3.8-flash"],
        key=lambda x: (0 if "lite" in x.lower() else (1 if "flash" in x.lower() else 2))
    )

    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "Convert the following Turkish or international drug/steroid/chemical name into its "
            "standard English INN/PubMed pharmacological name. "
            "If it is already in English, return it unchanged. "
            "Output ONLY the clean English name without quotes, explanations, or punctuation.\n"
            f"Name: {base_clean}"
        )
        for m_name in fast_models[:4]:
            try:
                resp = client.models.generate_content(model=m_name, contents=prompt)
                if resp and resp.text:
                    en_name = resp.text.strip().splitlines()[0].strip(" .\"'*`")
                    if 2 <= len(en_name) <= 60:
                        return en_name
            except Exception:
                continue
    except Exception:
        pass

    return base_clean

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

# --- PUBMED CANLI TARAMA (HIZ SINIRI KORUMALI + SON 10 YIL + EN GÜNCELE SIRALI + APA 7) ---
def search_pubmed(term1, term2, max_per_query=3, years_back=10):
    base_search = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    base_fetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    headers = {"User-Agent": "InSilicoToxPlatform/1.0 (academic-research)"}
    current_year = datetime.now().year

    def safe_get(url, params, as_json=True):
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=12)
                if r.status_code == 429:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                if r.status_code == 200:
                    return r.json() if as_json else r.content
            except Exception:
                time.sleep(0.8)
        return None

    def run_queries(start_yr=None):
        found_pmids = []
        notes = []
        date_filter = f' AND ("{start_yr}"[PDAT] : "{current_year}"[PDAT])' if start_yr else ""
        queries = [
            (f'({term1}) AND ({term2}){date_filter}', "Doğrudan Kombinasyon"),
            (f'({term1}) AND (hepatotoxicity OR liver OR toxicity){date_filter}', f"{term1} Toksisite"),
            (f'({term2}) AND (hepatotoxicity OR DILI OR liver toxicity){date_filter}', f"{term2} Toksisite")
        ]
        for idx, (q, label) in enumerate(queries):
            if idx > 0:
                time.sleep(0.45)
            params = {
                "db": "pubmed",
                "term": q,
                "retmode": "json",
                "retmax": max_per_query,
                "sort": "relevance",
                "tool": "InSilicoToxPlatform"
            }
            resp = safe_get(base_search, params, as_json=True)
            if resp:
                ids = resp.get("esearchresult", {}).get("idlist", [])
                if ids:
                    notes.append(f"{label}: {len(ids)}")
                    for pmid in ids:
                        if pmid not in found_pmids:
                            found_pmids.append(pmid)
        return found_pmids, notes

    start_year = current_year - years_back
    pmids, search_notes = run_queries(start_year)
    range_label = f"{start_year}–{current_year}"

    if len(pmids) < 2:
        time.sleep(0.6)
        fallback_start = current_year - 20
        pmids_20, notes_20 = run_queries(fallback_start)
        if len(pmids_20) > len(pmids):
            pmids = pmids_20
            search_notes = notes_20
            range_label = f"{fallback_start}–{current_year} (Son 10 yıl verisi kısıtlı olduğu için genişletildi)"

    if not pmids:
        time.sleep(0.6)
        pmids_all, notes_all = run_queries(None)
        if pmids_all:
            pmids = pmids_all
            search_notes = notes_all
            range_label = "Tüm Yıllar (Güncel veri kısıtlı olduğu için genişletildi)"

    if not pmids:
        return [], f"PubMed Sorgusu: {term1} + {term2} | {range_label} aralığında açık makale bulunamadı."

    articles = []
    time.sleep(0.45)
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(pmids[:8]),
        "retmode": "xml",
        "tool": "InSilicoToxPlatform"
    }
    xml_data = safe_get(base_fetch, fetch_params, as_json=False)
    if not xml_data:
        return [], "PubMed makale detayları çekilirken geçici bağlantı hatası oluştu."

    try:
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
        return [], f"PubMed XML işleme hatası: {str(e)}"

    articles.sort(key=lambda x: x["year_num"], reverse=True)
    summary_note = f"PubMed Sorgusu: {term1} + {term2} | Tarih: {range_label} | " + " • ".join(search_notes)
    return articles, summary_note

# --- YAPAY ZEKA ÇIKTISINI GÜVENLİ BÖLÜMLEME ---
def parse_ai_response(raw_text):
    def extract_tag(tag, text, allow_unclosed=False):
        if allow_unclosed:
            m = re.search(rf"\[{tag}\](.*?)(?:\[/{tag}\]|$)", text, re.DOTALL | re.IGNORECASE)
        else:
            m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    risk_level = extract_tag("RISK_SINIFI", raw_text)
    risk_summary = extract_tag("RISK_OZET", raw_text)
    notes_block = extract_tag("MAKALE_NOTLARI", raw_text)
    report = extract_tag("RAPOR", raw_text, allow_unclosed=True)

    if not report:
        cleaned = raw_text
        for tag in ["RISK_SINIFI", "RISK_OZET", "MAKALE_NOTLARI"]:
            cleaned = re.sub(rf"\[{tag}\].*?\[/{tag}\]", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        report = cleaned.strip()

    for tag in ["RISK_SINIFI", "RISK_OZET", "MAKALE_NOTLARI"]:
        report = re.sub(rf"\[{tag}\].*?\[/{tag}\]", "", report, flags=re.DOTALL | re.IGNORECASE)
    report = re.sub(r"\[/?(?:RISK_SINIFI|RISK_OZET|MAKALE_NOTLARI|RAPOR)\]", "", report, flags=re.IGNORECASE).strip()

    article_reasons = {}
    if notes_block:
        for line in notes_block.splitlines():
            m = re.match(r"[\s\-\*•]*(?:PMID\s*[:#-]?\s*)?(\d{5,9})[\*\s]*[:\-–—]\s*(.+)", line, re.IGNORECASE)
            if m:
                article_reasons[m.group(1).strip()] = m.group(2).strip().strip("*")

    return {
        "risk_level": risk_level.strip("* "),
        "risk_summary": risk_summary.strip("* "),
        "report": report,
        "article_reasons": article_reasons
    }

# --- GEMINI AI SENTEZ FONKSİYONU (MODEL SEÇİCİLİ & AKILLI YEDEKLEMELİ) ---
def generate_ai_report(
    substance1, substance2, scenario, articles,
    selected_model_option, available_models, allow_fallback=True,
    in_silico_context=None, pubmed_terms=None
):
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
    pubmed_block = f" (PubMed İngilizce Terimler: {pubmed_terms[0]} + {pubmed_terms[1]})" if pubmed_terms else ""

    prompt = f"""
Sen uzman bir klinik toksikolog ve farmakologsun. Aşağıdaki iki madde arasındaki olası ilaç-ilaç veya steroid-ilaç etkileşimini ve organ toksisitesi (özellikle hepatotoksisite / DILI) riskini akademik, net ve kanıta dayalı bir Türkçe ile analiz et.

**İncelenen Maddeler:** {substance1} + {substance2}{pubmed_block}
**Kullanım / Doz Senaryosu:** {scenario}
{silico_block}
**PubMed Canlı Literatür Taraması Sonuçları (En güncelden eskiye):**
{lit_text}

**ÇIKTI FORMATI (Aşağıdaki 4 etiketi açıp kapatarak KESİNLİKLE eksiksiz kullan):**

[RISK_SINIFI]
Sadece şu dördünden birini yaz: Kritik Risk, Yüksek Risk, Orta Risk veya Düşük Risk (Güvenli Profil)
[/RISK_SINIFI]

[RISK_OZET]
Bu risk sınıfının verilme nedenini tek, çarpıcı ve bilimsel bir cümleyle özetle.
[/RISK_OZET]

[MAKALE_NOTLARI]
Yukarıda verilen her bir PMID için, o makalenin bu analizle ne kadar uyumlu olduğunu ve neden kaynak olarak seçildiğini 1 kısa cümleyle alt alta şu formatta yaz:
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
        all_models = available_models if available_models else ["gemini-3.8-flash"]

        if selected_model_option == "⚡ Otomatik (En Güçlü Çalışan)":
            models_to_try = all_models[:10]
            manual_choice = None
        else:
            manual_choice = selected_model_option
            if allow_fallback:
                models_to_try = [manual_choice] + [m for m in all_models if m != manual_choice][:9]
            else:
                models_to_try = [manual_choice]

        last_error = ""
        for model_name in models_to_try:
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
                        parsed["fallback_used"] = bool(manual_choice and model_name != manual_choice)
                        parsed["requested_model"] = manual_choice
                        return parsed
                except Exception as e:
                    last_error = f"{model_name}: {str(e)}"
                    err_str = str(e).lower()
                    # Ücretli kota / erişim / bulunamadı hatalarında beklemeden anında sonraki modele geç
                    if any(k in err_str for k in ["limit: 0", "403", "404", "not_found", "permission", "billing"]):
                        break
                    # Geçici yoğunlukta 1 kez kısa bekle
                    if ("503" in err_str or "unavailable" in err_str) and attempt == 0:
                        time.sleep(1.5)
                        continue
                    break

        return {
            "ok": False,
            "error": (
                f"❌ Seçilen yapay zeka modeli şu an yanıt veremedi (ücretsiz kota sınırı veya geçici yoğunluk). "
                f"Sol menüden farklı bir model seçebilir veya 'Otomatik Yedekleme'yi açık bırakabilirsiniz.\n\n"
                f"Son teknik mesaj: {last_error}"
            )
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
    st.divider()
    st.markdown("### 📖 Kaynakça (APA 7 Formatı — En Güncelden Eskiye)")
    st.caption(note)
    if not articles:
        st.info("Bu sorgu için PubMed'den makale çekilemedi. Farklı bir etken madde yazımı ile tekrar deneyebilirsiniz.")
        return
    for idx, art in enumerate(articles, 1):
        st.markdown(f"{idx}. {art['apa']}")
        reason = article_reasons.get(art["pmid"])
        if reason:
            st.caption(f"🎯 **Seçim / Uyumluluk Nedeni:** {reason}")

# ==========================================================
# SOL MENÜ (SIDEBAR): MODEL SEÇİCİ & BİLİMSEL METODOLOJİ
# ==========================================================
available_models = get_available_models()

with st.sidebar:
    st.header("⚙️ Yapay Zeka & Sistem Ayarları")

    model_options = ["⚡ Otomatik (En Güçlü Çalışan)"] + available_models
    selected_model = st.selectbox(
        "🤖 Yapay Zeka Modeli",
        options=model_options,
        help="Otomatik mod, API anahtarınıza açık olan en güçlü modelden başlayarak yanıt verebilen ilk modeli seçer."
    )

    allow_fallback = st.checkbox(
        "Seçili model meşgulse yedek modele geç",
        value=True,
        help="Sunum sırasında yoğunluk (503) veya ücretli katman kotasına takılmamak için açık tutmanız önerilir."
    )

    st.caption(
        "💡 *Not: Pro / Carbon / Argon modelleri API'de ücretli (kullandığın kadar öde) katman gerektirebilir. "
        "Ücretsiz anahtarda sistem otomatik olarak en güçlü açık modele yönlenir.*"
    )

    st.divider()
    st.markdown("### ⚖️ Metodoloji & RAG Güvenilirliği")
    st.info(
        "**Kanıta Dayalı Mimari (RAG):** Bu platform, yapay zekanın ezberine güvenmek yerine "
        "NCBI **PubMed E-utilities** üzerinden son 10 yılın hakemli makale özetlerini canlı çeker, "
        "*in silico* verilerle (SwissADME / ProTox-III) sentezler ve her kaynağı tıklanabilir **APA 7 (DOI/PMID)** "
        "linkiyle doğrulanabilir biçimde sunar."
    )

# ==========================================================
# ANA UYGULAMA ARAYÜZÜ
# ==========================================================
st.title("🧪 In Silico & AI Toksisite Risk Analizi")
st.markdown("#### Farmasötik Toksikoloji Literatür Platformu")

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
                with st.spinner("Türkçe etken maddeler uluslararası PubMed terimlerine çevriliyor ve son 10 yıl taranıyor..."):
                    en_steroid = translate_drug_for_pubmed(selected_steroid, available_models)
                    en_drug = translate_drug_for_pubmed(selected_drug, available_models)
                    articles, note = search_pubmed(en_steroid, en_drug)

                    silico_summary = (
                        f"- Etiketlenen Risk Sınıfı: {risk_class}\n"
                        f"- Kombinasyon Mekanizması: {mekanizma}\n"
                        f"- Ek İlaç SwissADME CYP İnhibisyonu: {swiss}\n"
                        f"- Ek İlaç ProTox-III Hepatotoksisite: {protox}"
                    )
                    ai_res = generate_ai_report(
                        selected_steroid, selected_drug, selected_dose, articles,
                        selected_model, available_models, allow_fallback,
                        in_silico_context=silico_summary,
                        pubmed_terms=(en_steroid, en_drug)
                    )
                    if ai_res["ok"]:
                        st.caption(
                            f"**Aktif AI Modeli:** `{ai_res['model']}` | "
                            f"**PubMed Sorgu Terimleri:** `{en_steroid}` + `{en_drug}`"
                        )
                        if ai_res.get("fallback_used"):
                            st.info(
                                f"ℹ️ Seçtiğiniz `{ai_res['requested_model']}` modeli şu an meşgul veya ücretsiz kota dışında olduğu için "
                                f"otomatik olarak `{ai_res['model']}` modeli kullanıldı."
                            )
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
    st.markdown("Veri setinizde yer almayan herhangi iki etken maddeyi Türkçe veya İngilizce yazarak **PubMed (Son 10 Yıl) + Yapay Zeka** üzerinden anlık ön risk taraması yapabilirsiniz.")
    s_col1, s_col2, s_col3 = st.columns(3)
    with s_col1:
        custom_sub1 = st.text_input("1. Etken Madde (TR / EN)", placeholder="Örn: Trenbolon veya Trenbolone")
    with s_col2:
        custom_sub2 = st.text_input("2. Etken Madde (TR / EN)", placeholder="Örn: Parasetamol veya Isotretinoin")
    with s_col3:
        custom_scenario = st.selectbox(
            "Maruziyet Senaryosu",
            ["Kronik Uzun Süreli Maruziyet", "Supraterapötik Kür Dozu", "Terapötik Düşük Doz", "Akut Yüksek Doz Yüklemesi"]
        )

    if st.button("🚀 Canlı Literatür Tara ve Analiz Et", key="ai_btn_tab2"):
        if custom_sub1.strip() and custom_sub2.strip():
            with st.spinner(f"{custom_sub1} + {custom_sub2} için uluslararası PubMed literatürü taranıyor..."):
                en_sub1 = translate_drug_for_pubmed(custom_sub1.strip(), available_models)
                en_sub2 = translate_drug_for_pubmed(custom_sub2.strip(), available_models)
                articles, note = search_pubmed(en_sub1, en_sub2)

                ai_res = generate_ai_report(
                    custom_sub1.strip(), custom_sub2.strip(), custom_scenario, articles,
                    selected_model, available_models, allow_fallback,
                    pubmed_terms=(en_sub1, en_sub2)
                )
                if ai_res["ok"]:
                    st.divider()
                    st.subheader(f"📋 Canlı Analiz Raporu: {custom_sub1.strip()} + {custom_sub2.strip()}")
                    st.caption(
                        f"**Seçilen Senaryo:** {custom_scenario} | "
                        f"**Aktif AI Modeli:** `{ai_res['model']}` | "
                        f"**PubMed Sorgu Terimleri:** `{en_sub1}` + `{en_sub2}`"
                    )
                    if ai_res.get("fallback_used"):
                        st.info(
                            f"ℹ️ Seçtiğiniz `{ai_res['requested_model']}` modeli şu an meşgul veya ücretsiz kota dışında olduğu için "
                            f"otomatik olarak `{ai_res['model']}` modeli kullanıldı."
                        )

                    render_risk_banner(ai_res["risk_level"], ai_res["risk_summary"])
                    st.markdown(ai_res["report"])
                    render_bibliography(articles, note, ai_res["article_reasons"])
                else:
                    st.error(ai_res["error"])
        else:
            st.warning("Lütfen her iki etken madde kutusunu da doldurun.")

# --- ALT BİLGİ: BİLİMSEL METODOLOJİ & KARAR DESTEK UYARISI ---
st.divider()
with st.expander("⚖️ Bilimsel Metodoloji, Doğrulama Protokolü ve Yasal Uyarı"):
    st.markdown("""
    * **Canlı Literatür Destekli Sentez (RAG):** Yapay zeka yanıtları yalnızca modelin eğitim verisine dayanmaz; her sorguda **NCBI PubMed E-utilities API** aracılığıyla son 10 yılın hakemli makale özetleri (abstract) gerçek zamanlı taranır ve en güncelden eskiye sıralanır.
    * **Akut *In Silico* ve Kronik Maruziyet Farkı:** SwissADME ve ProTox-III gibi *in silico* tarama araçları ağırlıklı olarak akut yapısal toksisiteyi ve CYP450 inhibisyonunu modeller. Bu nedenle *in silico* taramada negatif görünen bir kombinasyon, uzun süreli kronik maruziyet, kümülatif oksidatif stres veya idiyosinkratik DILI mekanizmalarıyla klinik risk taşıyabilir.
    * **Kaynak Doğrulama:** Üretilen tüm akademik çıkarımlar metin içi APA 7 atıfları ve doğrudan tıklanabilir **DOI / PubMed** bağlantıları ile şeffaf biçimde denetlenebilir.
    * **Karar Destek Sınırı:** Bu platform, toksikoloji ve farmakoloji araştırmaları için geliştirilmiş bir *in silico* karar destek prototipidir; doğrudan klinik tanı, tedavi veya reçeteleme yerine geçmez.
    """)
