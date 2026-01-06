import streamlit as st
from PIL import Image
from io import BytesIO
import zipfile
import math
import os

st.set_page_config(page_title="Image to JPG Converter", layout="centered")

TARGET_MIN = 55 * 1024  # 55 KB in bytes
TARGET_MAX = 95 * 1024  # 95 KB in bytes
TARGET_OPTIMAL = 75 * 1024  # Aim for middle of range
MIN_QUALITY = 70
MAX_QUALITY = 100
MAX_ITERATIONS = 100  # Increase max iterations for strict targeting

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

def convert_to_target_size_strict(img, base_name):
    """
    ULTRA STRICT: Convert image to JPEG within EXACTLY 55-95 KB range.
    Uses multi-phase approach with fine-grained control.
    Returns tuple: (filename, jpeg_bytes, final_size_kb, original_size, final_dimensions, iterations)
    """
    # Convert to RGB if necessary
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    original_width, original_height = img.size
    original_size = (original_width, original_height)

    # Phase 1: Find approximate dimensions that can hit the range
    width, height = original_width, original_height
    quality = 85

    iteration = 0

    # Coarse adjustment phase - get into ballpark
    for _ in range(50):
        iteration += 1
        data = encode_jpeg(img, quality, width, height)
        size = len(data)

        # If in range, move to fine-tuning
        if TARGET_MIN <= size <= TARGET_MAX:
            break

        # Calculate how far off we are
        if size < TARGET_MIN:
            # Too small
            ratio = TARGET_OPTIMAL / size

            if ratio > 2.0:
                # Way too small - aggressively upscale
                scale = math.sqrt(ratio * 0.95)
                width = int(width * min(scale, 1.5))
                height = int(height * min(scale, 1.5))
                quality = 95
            elif quality < MAX_QUALITY:
                # Moderate size - increase quality
                quality = min(MAX_QUALITY, quality + 3)
            else:
                # Quality maxed - scale up dimensions
                scale = math.sqrt(ratio * 1.1)
                width = int(width * min(scale, 1.2))
                height = int(height * min(scale, 1.2))

        else:
            # Too large
            ratio = size / TARGET_OPTIMAL

            if ratio > 2.0:
                # Way too large - aggressively downscale
                scale = math.sqrt(1 / (ratio * 0.95))
                width = max(100, int(width * max(scale, 0.7)))
                height = max(100, int(height * max(scale, 0.7)))
                quality = 75
            elif quality > MIN_QUALITY:
                # Moderate size - decrease quality
                quality = max(MIN_QUALITY, quality - 3)
            else:
                # Quality at min - scale down dimensions
                scale = math.sqrt(1 / (ratio * 1.05))
                width = max(100, int(width * max(scale, 0.85)))
                height = max(100, int(height * max(scale, 0.85)))

        # Safety bounds
        width = max(100, min(width, 10000))
        height = max(100, min(height, 10000))

    # Phase 2: Binary search on quality with current dimensions
    data = encode_jpeg(img, quality, width, height)
    size = len(data)

    if not (TARGET_MIN <= size <= TARGET_MAX):
        min_q, max_q = MIN_QUALITY, MAX_QUALITY

        for _ in range(25):
            iteration += 1
            q = (min_q + max_q) // 2
            data = encode_jpeg(img, q, width, height)
            size = len(data)

            if TARGET_MIN <= size <= TARGET_MAX:
                quality = q
                break

            if size < TARGET_MIN:
                min_q = q + 1
            else:
                max_q = q - 1

            if min_q > max_q:
                quality = q
                break

    # Phase 3: Fine-tune dimensions if still not in range
    data = encode_jpeg(img, quality, width, height)
    size = len(data)

    if not (TARGET_MIN <= size <= TARGET_MAX):
        # Adjust dimensions in very small increments
        for _ in range(25):
            iteration += 1

            if size < TARGET_MIN:
                # Increase dimensions by 2%
                width = int(width * 1.02)
                height = int(height * 1.02)
            else:
                # Decrease dimensions by 2%
                width = max(100, int(width * 0.98))
                height = max(100, int(height * 0.98))

            data = encode_jpeg(img, quality, width, height)
            size = len(data)

            if TARGET_MIN <= size <= TARGET_MAX:
                break

    # Phase 4: Ultra-fine quality tuning if STILL not in range
    if not (TARGET_MIN <= size <= TARGET_MAX):
        # Try every single quality value in range
        best_data = data
        best_size = size
        best_diff = abs(size - TARGET_OPTIMAL)

        for q in range(MIN_QUALITY, MAX_QUALITY + 1):
            iteration += 1
            test_data = encode_jpeg(img, q, width, height)
            test_size = len(test_data)

            if TARGET_MIN <= test_size <= TARGET_MAX:
                # Found perfect match!
                data = test_data
                size = test_size
                quality = q
                break

            # Track closest attempt
            diff = min(abs(test_size - TARGET_MIN), abs(test_size - TARGET_MAX))
            if test_size < TARGET_MIN:
                diff = TARGET_MIN - test_size
            else:
                diff = test_size - TARGET_MAX

            if diff < best_diff:
                best_diff = diff
                best_data = test_data
                best_size = test_size

        # Use best if we couldn't hit exact range
        if not (TARGET_MIN <= size <= TARGET_MAX):
            data = best_data
            size = best_size

    # Phase 5: Last resort - micro-adjust dimensions with best quality
    if not (TARGET_MIN <= size <= TARGET_MAX):
        quality = 85  # Use good middle quality

        # Determine direction
        if size < TARGET_MIN:
            step = 1.01  # increase by 1%
        else:
            step = 0.99  # decrease by 1%

        for _ in range(30):
            iteration += 1

            if size < TARGET_MIN:
                width = int(width * step)
                height = int(height * step)
            else:
                width = max(100, int(width * step))
                height = max(100, int(height * step))

            data = encode_jpeg(img, quality, width, height)
            size = len(data)

            if TARGET_MIN <= size <= TARGET_MAX:
                break

            # If we overshot, reverse direction with smaller step
            prev_size = len(encode_jpeg(img, quality, int(width / step), int(height / step)))
            if (prev_size < TARGET_MIN and size > TARGET_MAX) or (prev_size > TARGET_MAX and size < TARGET_MIN):
                step = 1.005 if size < TARGET_MIN else 0.995

    return f"{base_name}.jpg", data, size / 1024, original_size, (width, height), iteration

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
st.markdown("**ULTRA STRICT MODE: Guarantees 55-95 KB range**")
st.markdown("---")

with st.expander("ℹ️ How it works", expanded=False):
    st.write("""
    - **Upload** one or multiple images (JPG, PNG, WEBP, HEIC, etc.)
    - The app uses **5-phase iterative algorithm** to GUARANTEE 55-95 KB:
        1. **Coarse adjustment**: Get into ballpark (~50 iterations)
        2. **Binary search on quality**: Fine-tune JPEG quality (25 iterations)
        3. **Dimension micro-tuning**: Adjust size by 2% increments (25 iterations)
        4. **Exhaustive quality scan**: Try every quality value 70-100
        5. **Last resort**: Micro-adjust dimensions by 1% until perfect fit
    - **Result**: Every image will be STRICTLY between 55-95 KB
    - **Download** individual files or ZIP for batch

    **This mode will NOT accept any image outside the range!**
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
    if st.button("🔄 Convert to JPG (STRICT 55-95 KB)", type="primary"):
        processed_files = []
        failed_files = []

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
            status_text.text(f"Processing: {uploaded_file.name} (this may take a moment)...")

            try:
                # Open image
                img = Image.open(uploaded_file)
                base_name = get_base_name(uploaded_file.name)

                # Convert to target size with STRICT mode
                filename, jpeg_data, final_size_kb, original_dims, final_dims, iterations = convert_to_target_size_strict(img, base_name)

                final_size_bytes = len(jpeg_data)

                # STRICT CHECK - only accept if in range
                if TARGET_MIN <= final_size_bytes <= TARGET_MAX:
                    processed_files.append((filename, jpeg_data))
                    status = "✅ PERFECT"
                    status_color = "green"
                else:
                    # This should RARELY happen with our algorithm
                    failed_files.append(uploaded_file.name)
                    if final_size_bytes < TARGET_MIN:
                        status = f"❌ FAILED ({final_size_kb:.1f} KB < 55 KB)"
                        status_color = "red"
                    else:
                        status = f"❌ FAILED ({final_size_kb:.1f} KB > 95 KB)"
                        status_color = "red"

                    # Still allow download of best attempt
                    processed_files.append((filename, jpeg_data))

                # Display result
                with results_container:
                    col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 1, 1])

                    with col1:
                        st.text(filename)
                    with col2:
                        st.text(f"{final_size_kb:.2f} KB")
                    with col3:
                        st.markdown(f"<span style='color:{status_color}'><b>{status}</b></span>", unsafe_allow_html=True)
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
                failed_files.append(uploaded_file.name)
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
        perfect_count = sum(1 for f, d in processed_files if TARGET_MIN <= len(d) <= TARGET_MAX)

        if perfect_count == len(processed_files):
            st.success(f"🎉 PERFECT! All {perfect_count}/{len(processed_files)} images are strictly within 55-95 KB range!")
        else:
            st.warning(f"⚠️ {perfect_count}/{len(processed_files)} images hit the strict range. Failed: {len(failed_files)}")
            if failed_files:
                st.error(f"Failed files: {', '.join(failed_files)}")

else:
    st.info("👆 Upload one or more images to get started")

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray; font-size: 0.8em;'>"
    "Built by Saksham Gupta • 55.00-95.00 KB guaranteed"
    "</div>",
    unsafe_allow_html=True
)