import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# App title
st.title("PDF Product Extractor")

# Upload PDF
uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])

if uploaded_file:
    # Show filename
    st.write(f"Processing: `{uploaded_file.name}`")

    # Refined patterns
    article_code_pattern = re.compile(r'\b\d{6,7}\b')
    price_pattern = re.compile(r'(\d{1,4},\d{2})\s*/pce', re.IGNORECASE)
    valid_context_pattern = re.compile(r'(DIN\s+(gauche|droite)|/pce|•|€|N°\s*d[’\'`]art)', re.IGNORECASE)

    data = []

    with pdfplumber.open(uploaded_file) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            lines = page.extract_text().split('\n')

            for i, line in enumerate(lines):
                if not valid_context_pattern.search(line):
                    continue

                code_match = article_code_pattern.search(line)
                price_match = price_pattern.search(line)

                if code_match:
                    code = code_match.group()
                    description_parts = []
                    j = i
                    while j >= 0 and len(description_parts) < 2:
                        description_parts.insert(0, lines[j].strip())
                        j -= 1
                    description = ' '.join(description_parts).strip()

                    price = None
                    if price_match:
                        price = price_match.group(1)
                    elif i + 1 < len(lines):
                        next_line_price = price_pattern.search(lines[i + 1])
                        if next_line_price:
                            price = next_line_price.group(1)

                    if price:
                        data.append({
                            'Page': page_num,
                            'Description': description,
                            'Article Code': code,
                            'Price (€)': price
                        })

    if data:
        df = pd.DataFrame(data)
        st.success(f"Extracted {len(df)} entries.")
        st.dataframe(df)

        # CSV export
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name="cleaned_spare_parts.csv",
            mime="text/csv",
        )
    else:
        st.warning("No matching data found in the PDF.")
