import streamlit as st
import pandas as pd
import re
import pdfplumber
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import white, black
from pypdf import PdfReader, PdfWriter

# Title
st.title("📝 MAJ Prix CPD")

# File upload
uploaded_pdf = st.file_uploader("Upload a PDF file", type=["pdf"])
uploaded_excel = st.file_uploader("Upload an Excel file (price list)", type=["xlsx"])

if uploaded_pdf and uploaded_excel:
    # Load prices
    price_df = pd.read_excel(uploaded_excel)
    price_df["Article"] = price_df["Article"].astype(str).str.strip()
    price_df["Prix510"] = price_df["Prix510"].astype(str).str.replace('.', ',').str.strip()
    price_map = dict(zip(price_df["Article"], price_df["Prix510"]))

    article_code_pattern = re.compile(r'\b\d{6,7}\b')
    price_pattern = re.compile(r'(\d{1,4},\d{2})\s*/pce', re.IGNORECASE)
    valid_context_pattern = re.compile(r'(DIN\s+(gauche|droite)|/pce|•|€|N°\s*d[’\'`]art)', re.IGNORECASE)

    updates_per_page = {}
    error_log = []

    def find_price_box_near_line(price_str, words, line_y0, tolerance=2):
        for w in words:
            if not w.get('text'):
                continue
            word_text = w['text'].replace(" ", "")
            if word_text.startswith(price_str):
                if abs(w['top'] - line_y0) <= tolerance:
                    return w
        return None

    with pdfplumber.open(uploaded_pdf) as pdf:
        for i, page in enumerate(pdf.pages):
            words = page.extract_words()
            lines = page.extract_text().split("\n")
            page_updates = []

            for line_index, line in enumerate(lines):
                if not valid_context_pattern.search(line):
                    continue

                code_match = article_code_pattern.search(line)
                price_match = price_pattern.search(line)

                if code_match:
                    code = code_match.group()
                    expected_price = price_map.get(code)

                    if not expected_price:
                        error_log.append({
                            "Page": i + 1,
                            "Article Code": code,
                            "Expected Price": "",
                            "Error Type": "Missing price",
                            "Context": line
                        })
                        continue

                    actual_price = None
                    if price_match:
                        actual_price = price_match.group(1)
                    elif line_index + 1 < len(lines):
                        next_line_price = price_pattern.search(lines[line_index + 1])
                        if next_line_price:
                            actual_price = next_line_price.group(1)

                    if not actual_price:
                        error_log.append({
                            "Page": i + 1,
                            "Article Code": code,
                            "Expected Price": expected_price,
                            "Error Type": "Price text not found on page",
                            "Context": line
                        })
                        continue

                    line_y0 = None
                    for w in words:
                        if code in w.get('text', ''):
                            line_y0 = w['top']
                            break

                    price_box = find_price_box_near_line(actual_price, words, line_y0) if line_y0 is not None else None

                    if not price_box:
                        nearby_words = [w['text'] for w in words if abs(w['top'] - line_y0) <= 2]
                        error_log.append({
                            "Page": i + 1,
                            "Article Code": code,
                            "Expected Price": expected_price,
                            "Error Type": "Price text location not found",
                            "Context": line,
                            "Nearby Words": ", ".join(nearby_words)
                        })
                        continue

                    page_updates.append((actual_price, expected_price, price_box))

            if page_updates:
                updates_per_page[i] = page_updates

    # Create overlays
    def create_overlay(page_width, page_height, updates):
        packet = BytesIO()
        c = canvas.Canvas(packet, pagesize=(page_width, page_height))
        for old_text, new_text, box in updates:
            x0 = box['x0']
            y0 = page_height - box['top']
            width = box['x1'] - box['x0']
            height = box['top'] - box['bottom']
            c.setFillColor(white)
            c.rect(x0, y0, width, height, fill=1, stroke=0)
            text_y = page_height - box['bottom'] + 1
            c.setFillColor(black)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x0, text_y, new_text + ",00n")
        c.save()
        packet.seek(0)
        return PdfReader(packet)

    # Merge overlays
    input_pdf_reader = PdfReader(uploaded_pdf)
    output_pdf_writer = PdfWriter()

    for i, page in enumerate(input_pdf_reader.pages):
        if i in updates_per_page:
            overlay = create_overlay(float(page.mediabox.width), float(page.mediabox.height), updates_per_page[i])
            page.merge_page(overlay.pages[0])
        output_pdf_writer.add_page(page)

    # Save output to BytesIO
    updated_pdf_bytes = BytesIO()
    output_pdf_writer.write(updated_pdf_bytes)
    updated_pdf_bytes.seek(0)

    st.success("✅ PDF updated successfully!")

    # Download button
    st.download_button(
        label="📥 Download updated PDF",
        data=updated_pdf_bytes,
        file_name="updated_catalog.pdf",
        mime="application/pdf"
    )

    # Display error log if any
    if error_log:
        st.warning(f"⚠️ {len(error_log)} issues found during processing.")
        error_df = pd.DataFrame(error_log)
        st.dataframe(error_df)
    else:
        st.info("🎉 No errors found. All articles were updated successfully.")
