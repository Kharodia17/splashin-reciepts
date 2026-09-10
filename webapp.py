import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import zipfile
import io
import re
import datetime

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

# Layout tuned for the new template (template-new.jpeg, 1600x1600).
BLACK = (0, 0, 0)
LEFT_MARGIN = 80       # x where wrapped continuation lines fall back to (flush with labels)
PAGE_RIGHT = 1550       # right-hand text boundary
LINE_HEIGHT = 65
FONT_SIZE = 54

RN_X, NAME_X, SUM_X, REASON_X, DATE_X = 1010, 560, 455, 510, 1175
# Several labels ("Received From", "The Sum Of", "Received For") use a
# decorative style with an oversized initial capital on each word, so their
# ink-TOP is set by that drop-cap rather than the shared line the rest of the
# label sits on. Aligning by ink-BOTTOM (the baseline, common to every label
# regardless of drop-caps) is what actually lines values up with labels.
RN_LABEL_BASELINE, NAME_LABEL_BASELINE, SUM_LABEL_BASELINE, REASON_LABEL_BASELINE, DATE_LABEL_BASELINE = 609, 726, 975, 1224, 1423

def get_fonts():
    """Load fonts safely, falling back to default if necessary."""
    try:
        font = ImageFont.truetype("arial.TTF", FONT_SIZE)
        return font
    except IOError:
        return ImageFont.load_default()

def _label_aligned_y(font, label_baseline):
    """Returns the y to pass to draw.text so the font's baseline (not a
    particular string's ink box, which varies with descenders like commas)
    lines up with a label's baseline."""
    ascent, _descent = font.getmetrics()
    return label_baseline - ascent

def wrap_text_multi_width(draw, text, font, first_width, rest_width):
    """Greedily wraps text on actual rendered pixel width (not character count),
    so long values never get cut off at the edge of the receipt. The first line
    can have a different width budget than the continuation lines."""
    words = text.split()
    if not words:
        return ['']
    lines = []
    current = ''
    limit = first_width
    for word in words:
        candidate = (current + ' ' + word).strip()
        if not current or draw.textlength(candidate, font=font) <= limit:
            current = candidate
        else:
            lines.append(current)
            current = word
            limit = rest_width
    if current:
        lines.append(current)
    return lines

def draw_wrapped_field(draw, text, font, x_first, y, line_height=LINE_HEIGHT,
                        x_wrap=LEFT_MARGIN, page_right=PAGE_RIGHT):
    """Draws text starting right after its label; if it's too long, continuation
    lines wrap down and fall back flush-left under the label instead of being cut off."""
    max_first = page_right - x_first
    max_wrap = page_right - x_wrap
    lines = wrap_text_multi_width(draw, text, font, max_first, max_wrap)
    y_cursor = y
    for i, line in enumerate(lines):
        x = x_first if i == 0 else x_wrap
        draw.text((x, y_cursor), line, fill=BLACK, font=font)
        y_cursor += line_height
    return y_cursor

def draw_sum_of(draw, raw_amount, font, x_first, y, line_height=LINE_HEIGHT,
                 x_wrap=LEFT_MARGIN, page_right=PAGE_RIGHT):
    """Draws 'The Sum Of' value. Supports a plain amount (e.g. 'R1000') or an
    amount with a bracketed breakdown (e.g. 'R1000 (R100 Cap R900 Fees)'), in
    which case each 'R<amount> <item>' piece is listed on its own bulleted line.
    Every line wraps on pixel width so nothing gets cut off."""
    match = re.search(r"(.*)\((.*)\)", raw_amount)

    if not match:
        draw_wrapped_field(draw, raw_amount, font, x_first, y, line_height, x_wrap, page_right)
        return

    main_amount = match.group(1).strip()
    breakdown_text = match.group(2).strip()

    y_cursor = draw_wrapped_field(draw, main_amount, font, x_first, y, line_height, x_wrap, page_right)

    # Extract items: "R[digits] [text]"
    body = breakdown_text if breakdown_text.startswith("R") else "R" + breakdown_text
    items = re.findall(r"(R\d+\s+[^R]+)", body)

    bullet_x = x_wrap + 20
    max_bullet = page_right - bullet_x
    for item in items:
        item_lines = wrap_text_multi_width(draw, f"- {item.strip()}", font, max_bullet, max_bullet)
        for line in item_lines:
            draw.text((bullet_x, y_cursor), line, fill=BLACK, font=font)
            y_cursor += line_height

def create_receipt_image(data, template_img):
    """Draws the receipt image with text wrapping and breakdown lists."""
    img = template_img.copy()
    draw = ImageDraw.Draw(img)
    font = get_fonts()

    # Parse Data
    name = str(data.get('name', '')).strip()
    amount = str(data.get('amount', '')).strip()
    reason = str(data.get('reason', '')).strip()
    breakdown = str(data.get('breakdown', '')).strip()
    rn = str(data.get('rn', '')).strip()
    date = str(data.get('date', '')).strip()

    # "The Sum Of" carries the amount plus its optional breakdown, e.g.
    # "R1000 (R100 Cap R900 Fees)". "Received For" stays a plain reason
    # (e.g. "swim fees") and is not mixed with the breakdown.
    raw_amount = f"{amount} ({breakdown})" if breakdown else amount

    rn_y = _label_aligned_y(font, RN_LABEL_BASELINE)
    name_y = _label_aligned_y(font, NAME_LABEL_BASELINE)
    sum_y = _label_aligned_y(font, SUM_LABEL_BASELINE)
    reason_y = _label_aligned_y(font, REASON_LABEL_BASELINE)
    date_y = _label_aligned_y(font, DATE_LABEL_BASELINE)

    draw.text((RN_X, rn_y), rn, fill=BLACK, font=font)
    draw_wrapped_field(draw, name, font, NAME_X, name_y)
    draw.text((DATE_X, date_y), date, fill=BLACK, font=font)

    draw_sum_of(draw, raw_amount, font, SUM_X, sum_y)
    draw_wrapped_field(draw, reason, font, REASON_X, reason_y)

    return img

def parse_consolidated_line(text_dump):
    """Parses bulk list into structured entries.

    Format: Name R[Amount] (optional breakdown) reason EFT|CASH
    Example: Kharodia's Abdul, Zahra, Saleemah R2070(R200 reg R400 goggles bal fees) swim fees EFT
    Example: Kharodia's Abdul, Zahra, Saleemah R1000 (R100 Cap R900 Fees) swim fees EFT
    """
    rows = []
    lines = text_dump.strip().split('\n')

    for line in lines:
        if not line.strip(): continue

        # Step 1: Extract payment type from end of line
        type_match = re.search(r'\b(EFT|CASH)\s*$', line.strip(), re.IGNORECASE)
        payment_type = type_match.group(1).upper() if type_match else 'EFT'
        remainder = line[:type_match.start()].strip() if type_match else line.strip()

        # Step 2: Extract amount + optional breakdown, e.g. R2070(R200 reg R400 goggles)
        # or R1000 (R100 Cap R900 Fees) - a space before the bracket is allowed.
        amount_match = re.search(r'(R\d+)\s*(\([^)]*\))?', remainder)

        if amount_match:
            name = remainder[:amount_match.start()].strip()
            amount = amount_match.group(1)
            breakdown_raw = amount_match.group(2) or ''
            # Strip surrounding brackets from breakdown e.g. "(R200 reg)" -> "R200 reg"
            breakdown = breakdown_raw.strip('()')
            reason_text = remainder[amount_match.end():].strip()
            rows.append({
                'rn': "",
                'date': datetime.datetime.now().strftime("%Y-%m-%d"),
                'name': name,
                'amount': amount,
                'breakdown': breakdown,
                'reason': reason_text,
                'type': payment_type
            })
        else:
            rows.append({
                'rn': "",
                'date': datetime.datetime.now().strftime("%Y-%m-%d"),
                'name': line[:20] + "...",
                'amount': "",
                'breakdown': "",
                'reason': line,
                'type': payment_type
            })
    return rows

# --- 2. USER INTERFACE ---

st.title("🏊 Splashin Receipt Generator")

# Sidebar
st.sidebar.header("Setup")
template_file = st.sidebar.file_uploader("Upload Template (jpg)", type=["jpg", "jpeg"])

if not template_file:
    st.info("👈 Please upload 'template-new.jpeg' in the sidebar to start.")
    st.stop()

template_image = Image.open(template_file)

# --- TABS ---
tab1, tab2 = st.tabs(["📝 Single Receipt", "📋 WhatsApp List"])

# --- TAB 1: SINGLE RECEIPT ---
with tab1:
    st.subheader("Create One Receipt")

    col1, col2 = st.columns(2)
    with col1:
        s_name = st.text_input("Name", placeholder="e.g. Kharodia's Abdul, Zahra")
        s_amount = st.text_input("Amount", value="R ")
        s_breakdown = st.text_input("Breakdown (optional)", placeholder="e.g. R200 reg R400 goggles bal fees")
    with col2:
        REASON_OPTIONS = ["swim fees", "aqua fees", "Custom..."]
        s_reason_select = st.selectbox("Reason", REASON_OPTIONS)
        if s_reason_select == "Custom...":
            s_reason = st.text_input("Custom Reason", placeholder="e.g. reg fees")
        else:
            s_reason = s_reason_select
        s_type = st.radio("Payment Type", ["EFT", "CASH"], horizontal=True)

    s_rn = st.text_input("Receipt No (RN)", value="1001")
    s_date = st.date_input("Date", datetime.datetime.now())

    if st.button("Generate Single Image", type="primary"):
        single_data = {
            'name': s_name,
            'amount': s_amount,
            'reason': s_reason,
            'breakdown': s_breakdown,
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
    st.markdown("Format: `Name R[Amount] (optional breakdown) swim fees|aqua fees EFT|CASH`")
    st.caption("Example: Kharodia's Abdul, Zahra, Saleemah R1000 (R100 Cap R900 Fees) swim fees EFT")

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
                "name": st.column_config.TextColumn("Name"),
                "amount": st.column_config.TextColumn("Amount", help="Shown on 'The Sum Of' line, together with Breakdown"),
                "breakdown": st.column_config.TextColumn("Breakdown", width="large", help="Shown on 'The Sum Of' line, e.g. R100 Cap R900 Fees"),
                "reason": st.column_config.SelectboxColumn(
                    "Reason", options=["swim fees", "aqua fees"], width="medium"
                ),
                "type": st.column_config.SelectboxColumn(
                    "Payment Type", options=["EFT", "CASH"]
                ),
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