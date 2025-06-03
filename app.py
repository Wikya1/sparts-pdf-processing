import re
import pdfplumber
import pandas as pd
import streamlit as st
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import white, black
from pypdf import PdfReader, PdfWriter
from io import BytesIO

st.title("📄 MaJ prix CPD")
st.write("Upload a PDF catalog and an Excel file of prices to update prices in the PDF.")

pdf_file = st.file_uploader("Upload PDF catalog", type=["pdf"])
excel_file = st.file_uploader("Upload Excel price list", type=["xlsx"])
werk_multiplier = st.number_input("WERK price multiplier", min_value=0.01, max_value=10.0, value=1.2, step=0.01)

if pdf_file and excel_file:
    with st.spinner("Processing..."):

        # Step 1: Load prices
        price_df = pd.read_excel(excel_file)
        price_df["Article"] = price_df["Article"].astype(str).str.strip()
        price_df["Prix510"] = price_df["Prix510"].astype(str).str.replace('.', ',').str.strip()
        price_map = dict(zip(price_df["Article"], price_df["Prix510"]))

        article_code_pattern = re.compile(r'\b\d{6,7}\b')
        price_pattern = re.compile(r'(\d{1,4},\d{2})\s*/(?:pce|m)', re.IGNORECASE) 
        valid_context_pattern = re.compile(r'(DIN\s+(gauche|droite)|/pce|•|€|N°\s*d[’\'`]art|WERK|ERSHT)', re.IGNORECASE)

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

        # Step 2: Read PDF and collect updates
        with pdfplumber.open(pdf_file) as pdf:
            for i, page in enumerate(pdf.pages):
                words = page.extract_words()
                lines = page.extract_text().split("\n")
                page_updates = []

                for line_index, line in enumerate(lines):
                    if not valid_context_pattern.search(line):
                        continue

                    code_match = article_code_pattern.search(line)
                    is_werk = "WERK" in line.upper() or "ERSHT" in line.upper()

                    if code_match:
                        code = code_match.group()
                        expected_price = price_map.get(code)
                    elif is_werk:
                        code = "WERK"
                        expected_price = None
                    else:
                        continue

                    # Find price on current or next line
                    price_match = price_pattern.search(line)
                    if not price_match and line_index + 1 < len(lines):
                        price_match = price_pattern.search(lines[line_index + 1])
                    if not price_match:
                        error_log.append({
                            "Page": i + 1,
                            "Article Code": code,
                            "Expected Price": expected_price,
                            "Error Type": "Price text not found on page",
                            "Context": line
                        })
                        continue

                    actual_price = price_match.group(1)

                    # Compute new price
                    if is_werk:
                        try:
                            numeric_price = float(actual_price.replace(',', '.'))
                            new_price = f"{round(numeric_price * werk_multiplier)}".replace('.', ',')
                        except:
                            error_log.append({
                                "Page": i + 1,
                                "Article Code": code,
                                "Expected Price": f"WERK x {werk_multiplier}",
                                "Error Type": "Invalid price format for WERK",
                                "Context": line
                            })
                            continue
                    else:
                        if not expected_price:
                            error_log.append({
                                "Page": i + 1,
                                "Article Code": code,
                                "Expected Price": "",
                                "Error Type": "Missing price in Excel",
                                "Context": line
                            })
                            continue
                        new_price = expected_price

                    # Estimate Y-position of line
                    line_y0 = None
                    for w in words:
                        if code in w.get('text', '') or (is_werk and ('WERK' in w.get('text', '').upper() or 'ERSHT' in w.get('text', '').upper())):
                            line_y0 = w['top']
                            break

                    if line_y0 is not None:
                        price_box = find_price_box_near_line(actual_price, words, line_y0)
                    else:
                        price_box = None

                    if not price_box:
                        nearby_words = [w['text'] for w in words if abs(w['top'] - line_y0) <= 2]
                        error_log.append({
                            "Page": i + 1,
                            "Article Code": code,
                            "Expected Price": new_price,
                            "Error Type": "Price text location not found",
                            "Context": line,
                            "Nearby Words": ", ".join(nearby_words)
                        })
                        continue

                    page_updates.append((actual_price, new_price, price_box))

                if page_updates:
                    updates_per_page[i] = page_updates

        # Step 3: Overlay creator
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

        # Step 4: Merge overlays
        input_pdf = PdfReader(pdf_file)
        output_pdf = PdfWriter()

        for i, page in enumerate(input_pdf.pages):
            if i in updates_per_page:
                overlay = create_overlay(float(page.mediabox.width), float(page.mediabox.height), updates_per_page[i])
                page.merge_page(overlay.pages[0])
            output_pdf.add_page(page)

        output_buffer = BytesIO()
        output_pdf.write(output_buffer)
        output_buffer.seek(0)

        st.success("✅ Price update complete!")

        # Step 5: Download + error log
        @st.fragment
        def download_fragment():
            st.download_button(
                label="📥 Download updated PDF",
                data=output_buffer,
                file_name="updated_catalog.pdf",
                mime="application/pdf"
            )
        
        download_fragment()

        if error_log:
            st.warning(f"⚠️ {len(error_log)} issues found.")
            error_df = pd.DataFrame(error_log)
            st.dataframe(error_df)
            error_csv = error_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download error log (CSV)", error_csv, "error_log.csv", "text/csv")
        else:
            st.success("🎉 No errors detected!")
