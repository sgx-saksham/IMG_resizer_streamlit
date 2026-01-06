import streamlit as st
from PIL import Image
from io import BytesIO
import zipfile
import math
import os

st.set_page_config(page_title="Image to JPG Converter", layout="wide")

TARGET_MIN = 55 * 1024  # 55 KB in bytes
TARGET_MAX = 95 * 1024  # 95 KB in bytes
MIN_QUALITY = 70
MAX_QUALITY = 100
MAX_ITERATIONS = 30  # Maximum attempts to hit target range

def get_base_name(filename):
    """Extract base name without extension"""
    return os.path.splitext(filename)[0]

def encode_jpeg(img, quality, width, height):
    """Encode image as JPEG with given quality and dimensions"""
    if (width, height) != img.size:
        resized = img.resize((width, height), Image.LANCZOS)
    else:
        resized = img

    buf = BytesIO()
    resized.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()

def convert_to_target_size(img, base_name):
    """
    Iteratively convert image to JPEG within strict 55-95 KB range.
    Returns tuple: (filename, jpeg_bytes, final_size_kb, original_size, final_dimensions, iterations)
    """
    # Convert to RGB if necessary
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    original_width, original_height = img.size
    original_size = (original_width, original_height)

    # Start with original dimensions and middle quality
    width, height = original_width, original_height
    quality = 85

    best_data = None
    best_size = float('inf')
    best_diff = float('inf')

    iteration = 0

    # Iterative refinement loop
    while iteration < MAX_ITERATIONS:
        iteration += 1

        # Encode with current parameters
        data = encode_jpeg(img, quality, width, height)
        size = len(data)

        # Check if we hit the target range
        if TARGET_MIN <= size <= TARGET_MAX:
            return f"{base_name}.jpg", data, size / 1024, original_size, (width, height), iteration

        # Track best attempt (closest to range)
        if size < TARGET_MIN:
            diff = TARGET_MIN - size
        else:
            diff = size - TARGET_MAX

        if diff < best_diff:
            best_diff = diff
            best_data = data
            best_size = size

        # Adjustment logic based on current size
        if size < TARGET_MIN:
            # Too small - need to increase size
            deficit_ratio = TARGET_MIN / size

            if quality < MAX_QUALITY:
                # First try increasing quality
                quality = min(MAX_QUALITY, quality + 5)
            else:
                # Quality maxed out, increase dimensions
                scale_factor = math.sqrt(deficit_ratio * 1.15)  # 15% margin
                scale_factor = min(scale_factor, 1.3)  # Don't scale too aggressively

                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)

                # Cap maximum dimensions to avoid memory issues
                MAX_DIM = 8000
                if new_width > MAX_DIM or new_height > MAX_DIM:
                    scale = MAX_DIM / max(new_width, new_height)
                    new_width = int(new_width * scale)
                    new_height = int(new_height * scale)

                width, height = new_width, new_height
                quality = 90  # Reset to high quality after upscaling

        else:
            # Too large - need to decrease size
            excess_ratio = size / TARGET_MAX

            if quality > MIN_QUALITY:
                # First try decreasing quality
                quality = max(MIN_QUALITY, quality - 5)
            else:
                # Quality at minimum, decrease dimensions
                scale_factor = math.sqrt(1 / (excess_ratio * 1.05))  # 5% margin
                scale_factor = max(scale_factor, 0.85)  # Don't scale too aggressively

                new_width = max(100, int(width * scale_factor))
                new_height = max(100, int(height * scale_factor))

                width, height = new_width, new_height
                quality = 80  # Reset to moderate quality after downscaling

        # Safety check for dimensions
        if width < 50 or height < 50:
            break

    # If we exhausted iterations, do final fine-tuning with binary search on quality
    if best_size is not None:
        # Determine if we're closer to min or max
        if best_size < TARGET_MIN:
            # Try to reach TARGET_MIN with current dimensions
            target = TARGET_MIN
            min_q, max_q = quality, MAX_QUALITY
        else:
            # Try to reach TARGET_MAX with current dimensions
            target = TARGET_MAX
            min_q, max_q = MIN_QUALITY, quality

        # Binary search on quality for final 10 iterations
        for _ in range(10):
            q = (min_q + max_q) // 2
            data = encode_jpeg(img, q, width, height)
            size = len(data)
            iteration += 1

            if TARGET_MIN <= size <= TARGET_MAX:
                return f"{base_name}.jpg", data, size / 1024, original_size, (width, height), iteration

            if abs(size - target) < best_diff:
                best_diff = abs(size - target)
                best_data = data
                best_size = size

            if size < target:
                min_q = q + 1
            else:
                max_q = q - 1

            if min_q > max_q:
                break

    # Return best attempt
    return f"{base_name}.jpg", best_data, best_size / 1024, original_size, (width, height), iteration

def create_zip(processed_files):
    """Create a ZIP file containing all processed images"""
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, data in processed_files:
            zip_file.writestr(filename, data)
    zip_buffer.seek(0)
    return zip_buffer

# UI
st.title("📸 Image to JPG Converter")
st.markdown("**Convert any image to JPG with strict target size: 55-95 KB**")
st.markdown("---")

with st.expander("ℹ️ How it works", expanded=False):
    st.write("""
    - **Upload** one or multiple images (JPG, PNG, WEBP, HEIC, etc.)
    - The app will **iteratively adjust** until the output is within **55-95 KB**:
        - Converts to JPG format
        - Adjusts quality (70-100%)
        - Upscales tiny images (increases resolution)
        - Downscales large images (decreases resolution)
        - Repeats up to 30+ iterations to hit target range
    - **Download** individual files or a ZIP for batch uploads

    **Algorithm:**
    - Too small? → Increase quality, then upscale dimensions
    - Too large? → Decrease quality, then downscale dimensions
    - Fine-tune with binary search to strictly hit 55-95 KB range
    """)

st.markdown("---")

# File uploader
uploaded_files = st.file_uploader(
    "Upload images",
    type=['jpg', 'jpeg', 'png', 'webp', 'bmp', 'gif', 'tiff', 'heic'],
    accept_multiple_files=True,
    help="Upload one or multiple images to convert"
)

if uploaded_files:
    st.success(f"✅ {len(uploaded_files)} file(s) uploaded")

    # Process button
    if st.button("🔄 Convert to JPG (55-95 KB)", type="primary"):
        processed_files = []

        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()

        # Results table header
        st.markdown("### 📊 Conversion Results")
        results_container = st.container()

        with results_container:
            col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 1, 1])
            with col1:
                st.markdown("**Filename**")
            with col2:
                st.markdown("**Final Size**")
            with col3:
                st.markdown("**Status**")
            with col4:
                st.markdown("**Iterations**")
            with col5:
                st.markdown("**Download**")
            st.markdown("---")

        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing: {uploaded_file.name}...")

            try:
                # Open image
                img = Image.open(uploaded_file)
                base_name = get_base_name(uploaded_file.name)

                # Convert to target size
                filename, jpeg_data, final_size_kb, original_dims, final_dims, iterations = convert_to_target_size(img, base_name)

                processed_files.append((filename, jpeg_data))

                # Determine status
                final_size_bytes = final_size_kb * 1024
                if TARGET_MIN <= final_size_bytes <= TARGET_MAX:
                    status = "✅ Perfect"
                    status_color = "green"
                elif final_size_bytes < TARGET_MIN:
                    status = "⚠️ Under"
                    status_color = "orange"
                else:
                    status = "⚠️ Over"
                    status_color = "orange"

                # Display result
                with results_container:
                    col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 1, 1])

                    with col1:
                        st.text(filename)
                    with col2:
                        st.text(f"{final_size_kb:.1f} KB")
                    with col3:
                        st.markdown(f"<span style='color:{status_color}'>{status}</span>", unsafe_allow_html=True)
                    with col4:
                        st.text(str(iterations))
                    with col5:
                        # Individual download button
                        st.download_button(
                            label="⬇️",
                            data=jpeg_data,
                            file_name=filename,
                            mime="image/jpeg",
                            key=f"download_{idx}_{filename}"
                        )

            except Exception as e:
                with results_container:
                    st.error(f"❌ Error processing {uploaded_file.name}: {str(e)}")

            # Update progress
            progress_bar.progress((idx + 1) / len(uploaded_files))

        status_text.text("✅ Processing complete!")
        progress_bar.empty()

        st.markdown("---")

        # Download all as ZIP if multiple files
        if len(processed_files) > 1:
            zip_data = create_zip(processed_files)
            st.download_button(
                label=f"📦 Download All as ZIP ({len(processed_files)} files)",
                data=zip_data,
                file_name="converted_images.zip",
                mime="application/zip",
                type="primary"
            )
        elif len(processed_files) == 1:
            filename, jpeg_data = processed_files[0]
            st.download_button(
                label=f"📥 Download {filename}",
                data=jpeg_data,
                file_name=filename,
                mime="image/jpeg",
                type="primary"
            )

        # Summary stats
        in_range = sum(1 for f, d in processed_files if TARGET_MIN <= len(d) <= TARGET_MAX)
        st.success(f"🎉 Successfully processed {len(processed_files)} image(s)! ({in_range}/{len(processed_files)} in perfect range)")

else:
    st.info("👆 Upload one or more images to get started")

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray; font-size: 0.8em;'>"
    "Built with Streamlit • Iterative conversion to strict 55-95 KB range"
    "</div>",
    unsafe_allow_html=True
)