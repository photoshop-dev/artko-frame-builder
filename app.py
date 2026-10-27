import os
import glob
import io
import re
import pandas as pd
from PIL import Image, ImageDraw, ImageOps
import streamlit as st

# 1. Page Config & Artko Brand Styling
st.set_page_config(page_title="Artko Frame & Mount Builder", page_icon="🖼️", layout="centered")

st.markdown("""
<style>
    .stApp {
        background-color: #F9F6F0;
        color: #3B322C;
        font-family: serif;
    }
    h1, h2, h3 {
        color: #3B322C !important;
        font-family: serif !important;
        font-weight: normal !important;
    }
    /* Force crisp, square corners on preview images */
    img {
        border-radius: 0px !important;
    }
    .stButton > button {
        background-color: #4A3B32 !important;
        color: #FFFFFF !important;
        border-radius: 4px !important;
        border: none !important;
        font-family: sans-serif !important;
        width: 100%;
    }
    .stButton > button:hover {
        background-color: #4A3B32 !important;
    }
    .stDownloadButton > button {
        background-color: #4A3B32 !important;
        color: #FFFFFF !important;
        border-radius: 4px !important;
        border: none !important;
        width: 100%;
    }
    .stAlert {
        background-color: #FFFFFF !important;
        border: 1px solid #E6E1DA !important;
        color: #3B322C !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("Artko Frame & Mount Builder")
st.markdown("Select a frame style, glass size, mount style, and upload your artwork to generate print-ready assets.")

folder_path = os.path.dirname(os.path.abspath(__file__))

# Helper function for smooth cross-fade blending across extensions to eliminate seams
def blend_horizontal_extension(source_strip, target_w):
    src_w, src_h = source_strip.size
    result = Image.new("RGBA", (target_w, src_h), (0, 0, 0, 0))
    
    x = 0
    while x < target_w:
        chunk_w = min(src_w, target_w - x)
        chunk = source_strip.crop((0, 0, chunk_w, src_h))
        
        if x == 0:
            result.paste(chunk, (x, 0))
        else:
            overlap = min(40, chunk_w, x)
            base_part = result.crop((x - overlap, 0, x, src_h))
            new_part = chunk.crop((0, 0, overlap, src_h))
            
            mask = Image.new("L", (overlap, src_h))
            for px_x in range(overlap):
                alpha_val = int(255 * (px_x / overlap))
                for px_y in range(src_h):
                    mask.putpixel((px_x, px_y), alpha_val)
            
            blended_overlap = Image.composite(new_part, base_part, mask)
            result.paste(blended_overlap, (x - overlap, 0))
            
            remaining_chunk = chunk.crop((overlap, 0, chunk_w, src_h))
            result.paste(remaining_chunk, (x + overlap, 0) if overlap < chunk_w else (x, 0))
            
        x += chunk_w
    
    if target_w > src_w:
        result = Image.new("RGBA", (target_w, src_h), (0, 0, 0, 0))
        x_pos = 0
        flip = False
        while x_pos < target_w:
            w_to_use = min(src_w, target_w - x_pos)
            part = source_strip.crop((0, 0, w_to_use, src_h))
            if flip:
                part = part.transpose(Image.FLIP_LEFT_RIGHT)
            result.paste(part, (x_pos, 0))
            x_pos += w_to_use
            flip = not flip
        return result
    return result

def blend_vertical_extension(source_strip, target_h):
    src_w, src_h = source_strip.size
    if target_h > src_h:
        result = Image.new("RGBA", (src_w, target_h), (0, 0, 0, 0))
        y_pos = 0
        flip = False
        while y_pos < target_h:
            h_to_use = min(src_h, target_h - y_pos)
            part = source_strip.crop((0, 0, src_w, h_to_use))
            if flip:
                part = part.transpose(Image.FLIP_TOP_BOTTOM)
            result.paste(part, (0, y_pos))
            y_pos += h_to_use
            flip = not flip
        return result
    return source_strip.crop((0, 0, src_w, target_h))

def parse_dims(size_str):
    nums = re.findall(r'\d+\.?\d*', str(size_str))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    return 0.0, 0.0

# 1. Auto-scan folder for Frame corners FIRST
frame_files = glob.glob(os.path.join(folder_path, "*_corner_*.png"))
frame_files = [f for f in frame_files if "mount" not in os.path.basename(f).lower()]

if not frame_files:
    st.error("❌ No frame corner PNGs found in folder.")
    st.stop()

frame_options = {}
for path in frame_files:
    filename = os.path.basename(path)
    try:
        width_str = filename.split('_')[-1].replace('.png', '')
        fcode = filename.split('_')[0].upper()
        label = f"{fcode} (Frame Width: {width_str}cm)"
        frame_options[label] = (filename, float(width_str), fcode)
    except ValueError:
        continue

sorted_frame_labels = sorted(frame_options.keys())

col_ctrl1, col_ctrl2 = st.columns(2)

with col_ctrl1:
    selected_frame_label = st.selectbox("1. Select Frame Style:", sorted_frame_labels)
    selected_fname, frame_width_cm, selected_fcode = frame_options[selected_frame_label]
    frame_corner_path = os.path.join(folder_path, selected_fname)
    frame_recess_cm = 0.5

# 2. Load CSV Sizes, Remove Duplicates, Sort Small to Large, Apply SQ/POR/LAND Naming
csv_path = os.path.join(folder_path, "glass_sizes.csv")
if not os.path.exists(csv_path):
    st.error("❌ 'glass_sizes.csv' not found in folder.")
    st.stop()

df = pd.read_csv(csv_path)

unique_sizes = []
seen_dim_sets = set()

for idx, row in df.iterrows():
    size_str = str(row['Glass Size']).strip()
    clean_val = size_str.lower().replace('cm', '').replace(' ', '')
    try:
        w_str, h_str = clean_val.split('x')
        w, h = float(w_str), float(h_str)
        dim_key = tuple(sorted([w, h]))
        if dim_key not in seen_dim_sets:
            seen_dim_sets.add(dim_key)
            
            if w == h:
                formatted_label = f"{int(w)} x {int(h)}cm SQ"
            elif w > h:
                formatted_label = f"{int(w)} x {int(h)}cm LAND"
            else:
                formatted_label = f"{int(w)} x {int(h)}cm POR"
                
            unique_sizes.append((w * h, w, h, formatted_label, size_str))
    except ValueError:
        continue

unique_sizes.sort(key=lambda x: x[0])
sorted_size_labels = [item[3] for item in unique_sizes]
size_lookup_map = {item[3]: (item[1], item[2], item[4]) for item in unique_sizes}

with col_ctrl1:
    selected_size_label = st.selectbox("2. Select Glass Size:", sorted_size_labels)

glass_w_cm, glass_h_cm, original_size_str = size_lookup_map[selected_size_label]

matched_rows = df[df['Glass Size'].astype(str).str.contains(str(int(glass_w_cm))) & df['Glass Size'].astype(str).str.contains(str(int(glass_h_cm)))]
if not matched_rows.empty:
    mount_width_cm = float(str(matched_rows.iloc[0]['Mount Width']).lower().replace('cm', '').strip())
else:
    mount_width_cm = 5.0

# 3. Auto-scan folder for Mount corners THIRD
mount_files = glob.glob(os.path.join(folder_path, "*mount*"))

mount_options = {"NONE": (None, 0.0)}
for path in mount_files:
    filename = os.path.basename(path)
    if not filename.endswith('.png'):
        continue
    try:
        width_str = filename.split('_')[-1].replace('.png', '')
        fname_lower = filename.lower()
        if "tint1" in fname_lower:
            label = "TINT1"
        else:
            label = "SNWTEX"
        mount_options[label] = (filename, float(width_str))
    except ValueError:
        continue

with col_ctrl2:
    selected_mount_label = st.selectbox("3. Select Mount Style:", list(mount_options.keys()))
    selected_mname, mount_asset_width_cm = mount_options[selected_mount_label]
    
    uploaded_art = st.file_uploader("4. Upload Artwork (Optional)", type=["png", "jpg", "jpeg", "tif", "tiff"])

st.markdown("---")

# 5. Generate Button & Logic
if st.button("🚀 Generate Framed Asset", type="primary"):
    with st.spinner("Assembling frame and artwork..."):
        pixels_per_cm = 150 / 2.54
        
        frame_extra_cm = frame_width_cm - frame_recess_cm
        
        overall_w_cm = glass_w_cm + (2 * frame_extra_cm)
        overall_h_cm = glass_h_cm + (2 * frame_extra_cm)
        canvas_w = int(overall_w_cm * pixels_per_cm)
        canvas_h = int(overall_h_cm * pixels_per_cm)

        # Initialize canvas with transparent background (0,0,0,0) instead of solid white
        final_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

        glass_pixel_w = int(glass_w_cm * pixels_per_cm)
        glass_pixel_h = int(glass_h_cm * pixels_per_cm)
        glass_box_left = int(frame_extra_cm * pixels_per_cm)
        glass_box_top = int(frame_extra_cm * pixels_per_cm)

        # --- A. BUILD INNER ARTWORK LAYER (Resized to Print Size if Mount is present) ---
        if uploaded_art is not None:
            art_img = Image.open(uploaded_art).convert("RGBA")
            
            if selected_mname is not None:
                print_size_str = str(matched_rows.iloc[0]['Print Size']) if not matched_rows.empty else f"{glass_w_cm}cm x {glass_h_cm}cm"
                pw_cm, ph_cm = parse_dims(print_size_str)
                if pw_cm == 0 or ph_cm == 0:
                    pw_cm, ph_cm = glass_w_cm, glass_h_cm
                
                art_pixel_w = int(pw_cm * pixels_per_cm)
                art_pixel_h = int(ph_cm * pixels_per_cm)
                
                aperture_offset_x = int((glass_w_cm - pw_cm) / 2.0 * pixels_per_cm)
                aperture_offset_y = int((glass_h_cm - ph_cm) / 2.0 * pixels_per_cm)
                
                art_box_left = glass_box_left + aperture_offset_x
                art_box_top = glass_box_top + aperture_offset_y
                
                art_fitted = ImageOps.fit(art_img, (art_pixel_w, art_pixel_h), method=Image.Resampling.LANCZOS)
                final_canvas.paste(art_fitted, (art_box_left, art_box_top))
            else:
                art_fitted = ImageOps.fit(art_img, (glass_pixel_w, glass_pixel_h), method=Image.Resampling.LANCZOS)
                final_canvas.paste(art_fitted, (glass_box_left, glass_box_top))

        # --- B. BUILD MOUNT LAYER ---
        if selected_mname is not None:
            mount_corner_path = os.path.join(folder_path, selected_mname)
            mount_img_src = Image.open(mount_corner_path).convert("RGBA")
            mount_moulding_px = int(mount_asset_width_cm * pixels_per_cm)
            
            mc_w, mc_h = mount_img_src.size
            if mount_moulding_px > mc_w:
                mount_moulding_px = mc_w

            mtl = mount_img_src.crop((0, 0, mount_moulding_px, mount_moulding_px))
            mtr = mtl.transpose(Image.FLIP_LEFT_RIGHT)
            mbl = mtl.transpose(Image.FLIP_TOP_BOTTOM)
            mbr = mtl.transpose(Image.ROTATE_180)

            mount_box_left = glass_box_left
            mount_box_top = glass_box_top
            mount_box_right = glass_box_left + glass_pixel_w
            mount_box_bottom = glass_box_top + glass_pixel_h
            mount_box_w = glass_pixel_w
            mount_box_h = glass_pixel_h

            mount_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            mount_layer.paste(mtl, (mount_box_left, mount_box_top), mtl)
            mount_layer.paste(mtr, (mount_box_right - mount_moulding_px, mount_box_top), mtr)
            mount_layer.paste(mbl, (mount_box_left, mount_box_bottom - mount_moulding_px), mbl)
            mount_layer.paste(mbr, (mount_box_right - mount_moulding_px, mount_box_bottom - mount_moulding_px), mbr)

            mgap_w = mount_box_w - (2 * mount_moulding_px)
            mgap_h = mount_box_h - (2 * mount_moulding_px)

            if mgap_w > 0 and mgap_h > 0:
                m_slice_h = mount_img_src.crop((mount_moulding_px, 0, mount_img_src.width - mount_moulding_px, mount_moulding_px))
                m_top = blend_horizontal_extension(m_slice_h, mgap_w)
                mount_layer.paste(m_top, (mount_box_left + mount_moulding_px, mount_box_top), m_top)
                
                m_bot = m_top.transpose(Image.FLIP_TOP_BOTTOM)
                mount_layer.paste(m_bot, (mount_box_left + mount_moulding_px, mount_box_bottom - mount_moulding_px), m_bot)

                m_slice_v = mount_img_src.crop((0, mount_moulding_px, mount_moulding_px, mount_img_src.height - mount_moulding_px))
                m_left = blend_vertical_extension(m_slice_v, mgap_h)
                mount_layer.paste(m_left, (mount_box_left, mount_box_top + mount_moulding_px), m_left)
                
                m_right = m_left.transpose(Image.FLIP_LEFT_RIGHT)
                mount_layer.paste(m_right, (mount_box_right - mount_moulding_px, mount_box_top + mount_moulding_px), m_right)

            final_canvas.paste(mount_layer, (0, 0), mount_layer)

        # --- C. BUILD FRAME MOULDING LAYER ---
        frame_img_src = Image.open(frame_corner_path).convert("RGBA")
        frame_moulding_px = int(frame_width_cm * pixels_per_cm)
        fc_w, fc_h = frame_img_src.size
        if frame_moulding_px > fc_w:
            frame_moulding_px = fc_w

        ftl = frame_img_src.crop((0, 0, frame_moulding_px, frame_moulding_px))
        ftr = ftl.transpose(Image.FLIP_LEFT_RIGHT)
        fbl = ftl.transpose(Image.FLIP_TOP_BOTTOM)
        fbr = ftl.transpose(Image.ROTATE_180)

        frame_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        frame_layer.paste(ftl, (0, 0), ftl)
        frame_layer.paste(ftr, (canvas_w - frame_moulding_px, 0), ftr)
        frame_layer.paste(fbl, (0, canvas_h - frame_moulding_px), fbl)
        frame_layer.paste(fbr, (canvas_w - frame_moulding_px, canvas_h - frame_moulding_px), fbr)

        fgap_w = canvas_w - (2 * frame_moulding_px)
        fgap_h = canvas_h - (2 * frame_moulding_px)

        if fgap_w > 0 and fgap_h > 0:
            f_slice_h = frame_img_src.crop((frame_moulding_px, 0, frame_img_src.width - frame_moulding_px, frame_moulding_px))
            f_top = blend_horizontal_extension(f_slice_h, fgap_w)
            frame_layer.paste(f_top, (frame_moulding_px, 0), f_top)
            
            f_bot = f_top.transpose(Image.FLIP_TOP_BOTTOM)
            frame_layer.paste(f_bot, (frame_moulding_px, canvas_h - frame_moulding_px), f_bot)

            f_slice_v = frame_img_src.crop((0, frame_moulding_px, frame_moulding_px, frame_img_src.height - frame_moulding_px))
            f_left = blend_vertical_extension(f_slice_v, fgap_h)
            frame_layer.paste(f_left, (0, frame_moulding_px), f_left)
            
            f_right = f_left.transpose(Image.FLIP_LEFT_RIGHT)
            frame_layer.paste(f_right, (canvas_w - frame_moulding_px, frame_moulding_px), f_right)

        if selected_mname is not None:
            shadow_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            draw_sh = ImageDraw.Draw(shadow_layer)
            
            edge_offset = frame_moulding_px
            draw_sh.rectangle(
                [edge_offset, edge_offset, canvas_w - edge_offset, canvas_h - edge_offset],
                outline=(0, 0, 0, 50),
                width=3
            )
            frame_layer = Image.alpha_composite(shadow_layer, frame_layer)

        final_canvas = Image.alpha_composite(final_canvas, frame_layer)

        # Save to memory buffer
        suffix = selected_mount_label.lower()
        output_name = f"output_{selected_fcode}_{int(glass_w_cm)}x{int(glass_h_cm)}_{suffix}.png"
        
        buf = io.BytesIO()
        final_canvas.save(buf, format="PNG", dpi=(150, 150))
        byte_im = buf.getvalue()

        st.success(f"✅ Asset generated successfully in memory!")
        st.image(byte_im, caption=f"{selected_fcode} Frame with {selected_mount_label} mount for {selected_size_label}", use_container_width=True)
        
        st.download_button(
            label="📥 Download Ready-to-Use PNG",
            data=byte_im,
            file_name=output_name,
            mime="image/png"
        )