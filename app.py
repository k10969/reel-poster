import streamlit as st
import os
from pathlib import Path
from poster_core_reel import PosterCoreReel, SUPPORTED_EXTS
from moviepy.editor import VideoFileClip
import random
import datetime

# ランダムテキストを random_texts.txt から読み込む
with open("random_texts.txt", "r", encoding="utf-8") as f:
    random_texts = [line.strip() for line in f if line.strip()]

# 素材をリフレッシュする関数
def _refresh_materials():
    material_dir = os.path.join(os.getenv("PERSISTENT_DIR", "./"), "overlay_input")
    if not os.path.exists(material_dir):
        os.makedirs(material_dir)
    materials = []
    for f in os.listdir(material_dir):
        if Path(f).suffix.lower() in SUPPORTED_EXTS:
            file_path = os.path.join(material_dir, f)
            size_kb = os.path.getsize(file_path) / 1024
            thumbnail = None
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
                thumbnail = file_path
            elif f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".mpeg4")):
                try:
                    with VideoFileClip(file_path) as clip:
                        thumb_path = os.path.join(material_dir, f"{f}_thumb.jpg")
                        clip.save_frame(thumb_path)
                        thumbnail = thumb_path
                except Exception as e:
                    st.warning(f"{f} のサムネイル生成に失敗: {e}")
            comment_key = f"{f}_comment"
            comment = st.session_state.get(comment_key, "")
            if not comment and random_texts:
                comment = random.choice(random_texts)
            materials.append({"File Name": f, "Size": f"{size_kb:.1f} KB", "Thumbnail": thumbnail, "Comment": comment})
    return materials

# カスタム CSS
st.markdown("""
    <style>
    .main {
        background: linear-gradient(135deg, #f0f4f8, #e0e8f0);
        padding: 20px;
        border-radius: 10px;
    }
    .upload-box {
        border: 2px dashed #ff6b6b;
        padding: 30px;
        background-color: #fff;
        border-radius: 15px;
        text-align: center;
        transition: all 0.3s ease;
    }
    .upload-box.dragover {
        background-color: #ffebee;
        border-color: #ff3333;
    }
    .material-card {
        background: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 15px;
        transition: transform 0.2s;
    }
    .material-card:hover {
        transform: translateY(-5px);
    }
    .material-thumbnail {
        width: 120px;
        height: 120px;
        object-fit: cover;
        border-radius: 8px;
    }
    .comment-area {
        background: #fff3e6;
        padding: 10px;
        border-radius: 8px;
        border: 1px solid #ff9800;
    }
    .stButton > button {
        background-color: #ff6b6b;
        color: white;
        border-radius: 8px;
        padding: 5px 15px;
        transition: background-color 0.3s;
    }
    .stButton > button:hover {
        background-color: #ff4040;
    }
    </style>
""", unsafe_allow_html=True)

def main():
    st.markdown('<div class="main">', unsafe_allow_html=True)
    st.title("Reel Poster App 🎥")

    # 2列レイアウト（アップロードを左、素材リストを右）
    col1, col2 = st.columns([1, 2])

    # 素材アップロード（左側）
    with col1:
        st.subheader("素材アップロード")
        upload_container = st.empty()
        with upload_container.container():
            st.markdown('<div class="upload-box" id="upload-drop">ドラッグ＆ドロップでアップロード</div>', unsafe_allow_html=True)
            uploaded_files = st.file_uploader(
                "ファイルを選択（200MBまで）",
                accept_multiple_files=True,
                type=[ext[1:] for ext in SUPPORTED_EXTS],
                key="file_uploader"
            )
            if uploaded_files:
                material_dir = os.path.join(os.getenv("PERSISTENT_DIR", "./"), "overlay_input")
                for file in uploaded_files:
                    with open(os.path.join(material_dir, file.name), "wb") as f:
                        f.write(file.getbuffer())
                    st.success(f"{file.name} をアップロードしました")
                st.rerun()

    # 素材リスト（右側）
    with col2:
        st.subheader("素材リスト")
        materials = _refresh_materials()
        if materials:
            for material in materials:
                with st.container():
                    st.markdown('<div class="material-card">', unsafe_allow_html=True)
                    col_thumb, col_info = st.columns([1, 2])
                    with col_thumb:
                        if material["Thumbnail"]:
                            st.image(material["Thumbnail"], caption=material["File Name"], use_column_width=False, width=120, output_format="auto")
                        else:
                            st.write(f"サムネイルなし: {material['File Name']}")
                    with col_info:
                        st.markdown('<div class="comment-area">', unsafe_allow_html=True)
                        comment_key = f"{material['File Name']}_comment"
                        comment = st.text_area("コメント", value=material["Comment"], key=comment_key, height=100)
                        st.session_state[comment_key] = comment
                        st.write(f"サイズ: {material['Size']}")
                        if st.button("保存", key=f"save_{material['File Name']}"):
                            st.session_state[comment_key] = comment
                            st.success("コメントが保存されました")
                        if st.button("削除", key=f"delete_{material['File Name']}"):
                            os.remove(os.path.join(os.getenv("PERSISTENT_DIR", "./"), "overlay_input", material["File Name"]))
                            if material["Thumbnail"] and os.path.exists(material["Thumbnail"]):
                                os.remove(material["Thumbnail"])
                            st.success(f"{material['File Name']} を削除しました")
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.write("素材がありません")

    st.markdown('</div>', unsafe_allow_html=True)

if __name__ == "__main__":
    main()
