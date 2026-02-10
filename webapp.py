import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import zipfile
import io
import re
import datetime
import textwrap

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Splashin Receipts", 
    page_icon="🏊", 
    layout="wide"
)

# --- SESSION STATE SETUP ---
# This ensures the data doesn't disappear while you are editing the table
if 'whatsapp_data' not in st.session_state:
    st.session_state.whatsapp_data = None

# --- 1. CORE FUNCTIONS ---

def get_fonts():
    """Load fonts safely, falling back to default if necessary."""
    try:
        font = ImageFont.truetype("arial.ttf", 18)
        check_font = ImageFont.truetype("arial.ttf", 22)
        return font, check_font
    except IOError:
        return ImageFont.load_default(), ImageFont.load_default()

def create_receipt_image(data, template_img):
    """Draws the receipt image with text wrapping and breakdown lists."""
    img = template_img.copy()
    draw = ImageDraw.Draw(img)
    font, check_font = get_fonts()
    black = (0, 0, 0)
    
    # Parse Data
    name = str(data.get('name', ''))
    amount = str(data.get('amount', ''))
    raw_reason = str(data.get('reason', ''))
    rn = str(data.get('rn', ''))
    date = str(data.get('date', ''))
    
    # Draw Checkbox
    payment_type = str(data.get('type', 'EFT')).strip().upper()
    if 'CASH' in payment_type:
        draw.text((97, 172), "X", fill=black, font=check_font) 
    else:
        draw.text((197, 172), "X", fill=black, font=check_font)

    # Draw Standard Fields
    draw.text((400, 185), rn, fill=black, font=font)
    draw.text((260, 225), name, fill=black, font=font)
    draw.text((260, 290), amount, fill=black, font=font)
    draw.text((400, 443), date, fill=black, font=font)

    # --- SMART FORMATTING FOR 'RECEIVED FOR' ---
    x_start = 260
    y_start = 355
    line_height = 20

    # Check for breakdown inside brackets: "Feb (R675 Sadia ...)"
    match = re.search(r"(.*)\((.*)\)", raw_reason)
    
    if match:
        main_reason = match.group(1).strip()
        breakdown_text = match.group(2).strip()
        
        # Draw Main Reason (e.g., "Feb")
        draw.text((x_start, y_start), main_reason, fill=black, font=font)
        y_cursor = y_start + line_height
        
        # Extract items: "R[digits] [text]"
        items = re.findall(r"(R\d+\s+[^R]+)", "R" + breakdown_text if not breakdown_text.strip().startswith("R") else breakdown_text)
        
        # Draw List
        for item in items:
            draw.text((x_start + 10, y_cursor), f"- {item.strip()}", fill=black, font=font)
            y_cursor += line_height
            
    else:
        # Standard Wrapping
        wrapped_lines = textwrap.wrap(raw_reason, width=45)
        for i, line in enumerate(wrapped_lines):
            draw.text((x_start, y_start + (i * line_height)), line, fill=black, font=font)

    return img

def parse_consolidated_line(text_dump):
    """Parses WhatsApp dump into structured list."""
    rows = []
    lines = text_dump.strip().split('\n')
    
    for line in lines:
        if not line.strip(): continue
        # Regex: Name ... R(digits) ... Reason
        match = re.search(r"^(.*?)\s+(R\d+)\s+(.*)$", line.strip())
        
        if match:
            rows.append({
                'rn': "",
                'date': datetime.datetime.now().strftime("%Y-%m-%d"),
                'name': match.group(1).strip(),
                'amount': match.group(2).strip(),
                'reason': match.group(3).strip(),
                'type': 'EFT'
            })
        else:
            rows.append({
                'rn': "",
                'date': datetime.datetime.now().strftime("%Y-%m-%d"),
                'name': line[:20] + "...",
                'amount': "",
                'reason': line,
                'type': 'EFT'
            })
    return rows

# --- 2. USER INTERFACE ---

st.title("🏊 Splashin Receipt Generator")

# Sidebar
st.sidebar.header("Setup")
template_file = st.sidebar.file_uploader("Upload Template (jpg)", type=["jpg", "jpeg"])

if not template_file:
    st.info("👈 Please upload 'template.jpg' in the sidebar to start.")
    st.stop()

template_image = Image.open(template_file)

# --- TABS ---
tab1, tab2 = st.tabs(["📝 Single Receipt", "📋 WhatsApp List"])

# --- TAB 1: SINGLE RECEIPT ---
with tab1:
    st.subheader("Create One Receipt")
    
    col1, col2 = st.columns(2)
    with col1:
        s_name = st.text_input("Name", placeholder="e.g. Fatima Patel")
        s_amount = st.text_input("Amount", value="R ")
        s_type = st.radio("Payment Type", ["EFT", "CASH"], horizontal=True)
    with col2:
        s_reason = st.text_area("Reason", placeholder="e.g. Feb (R675 Sadia R675 Fatima)", height=100)
        s_rn = st.text_input("Receipt No (RN)", value="1001")
        s_date = st.date_input("Date", datetime.datetime.now())

    if st.button("Generate Single Image", type="primary"):
        single_data = {
            'name': s_name,
            'amount': s_amount,
            'reason': s_reason,
            'rn': s_rn,
            'type': s_type,
            'date': s_date.strftime("%Y-%m-%d")
        }
        
        final_img = create_receipt_image(single_data, template_image)
        
        st.image(final_img, caption=f"Preview: Receipt #{s_rn}", width=400)
        
        img_buffer = io.BytesIO()
        final_img.save(img_buffer, format="JPEG")
        safe_name = s_name.replace(" ", "_")
        
        st.download_button(
            label="📥 Download Image",
            data=img_buffer.getvalue(),
            file_name=f"Receipt_{s_rn}_{safe_name}.jpg",
            mime="image/jpeg"
        )

# --- TAB 2: WHATSAPP LIST (UPDATED WITH FORM) ---
with tab2:
    st.subheader("Paste WhatsApp List")
    st.markdown("Format: `Name R[Amount] Reason`")
    st.caption("Example: Ebrahims R2025 Feb (R675 sadia aqua R675 Faatima R675 Mo)")

    # 1. THE INPUT FORM
    with st.form("whatsapp_input_form"):
        raw_text = st.text_area("Paste here:", height=100)
        submitted = st.form_submit_button("Analyze List", type="primary")
        
        if submitted and raw_text:
            # Parse and save to session state so it persists
            st.session_state.whatsapp_data = parse_consolidated_line(raw_text)

    # 2. THE EDITABLE TABLE (Displayed if data exists)
    if st.session_state.whatsapp_data:
        st.success(f"✅ Loaded {len(st.session_state.whatsapp_data)} entries. Edit details below:")
        
        # Clear Button
        if st.button("🔄 Clear List"):
            st.session_state.whatsapp_data = None
            st.rerun()

        # The Table
        edited_df = st.data_editor(
            pd.DataFrame(st.session_state.whatsapp_data),
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "rn": st.column_config.TextColumn("Receipt No (Required)", help="Enter RN manually"),
                "date": st.column_config.TextColumn("Date"),
                "amount": st.column_config.TextColumn("Amount"),
                "name": st.column_config.TextColumn("Name"),
                "reason": st.column_config.TextColumn("Reason", width="large"),
            },
            key="editor" # Unique key for the widget
        )
        
        # 3. GENERATE BUTTON
        if st.button("🚀 Generate Bulk Receipts"):
            final_data = edited_df.to_dict('records')
            
            if any(not str(row['rn']).strip() for row in final_data):
                st.warning("⚠️ Please fill in the Receipt Number (RN) for all rows.")
            else:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                    progress_bar = st.progress(0)
                    for i, row in enumerate(final_data):
                        img = create_receipt_image(row, template_image)
                        
                        img_buf = io.BytesIO()
                        img.save(img_buf, format="JPEG")
                        
                        fname = f"Receipt_{row['rn']}_{str(row['name']).replace(' ', '_')}.jpg"
                        zip_file.writestr(fname, img_buf.getvalue())
                        progress_bar.progress((i + 1) / len(final_data))
                
                st.success("All receipts generated successfully!")
                st.download_button(
                    label="📥 Download ZIP File",
                    data=zip_buffer.getvalue(),
                    file_name="Splashin_Receipts.zip",
                    mime="application/zip"
                )