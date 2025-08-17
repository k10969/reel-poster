import streamlit as st
import os
from pathlib import Path
from poster_core_reel import PosterCoreReel, SUPPORTED_EXTS
from moviepy.editor import VideoFileClip  # moviepy==1.0.3 で動作確認
import random
import datetime

# ランダムコメントを random_texts.txt から読み込む
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
            # サムネイル生成
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
            # コメント（空の場合はランダム選択、session_state で保存）
            comment_key = f"{f}_comment"
            comment = st.session_state.get(comment_key, "")
            if not comment and random_texts:
                comment = random.choice(random_texts)
            materials.append({"File Name": f, "Size": f"{size_kb:.1f} KB", "Thumbnail": thumbnail, "Comment": comment})
    return materials

# カスタム CSS
st.markdown("""
    <style>
    .upload-box {
        border: 2px dashed #4CAF50;
        padding: 20px;
        background-color: #f9f9f9;
        border-radius: 10px;
        text-align: center;
    }
    .material-row {
        display: flex;
        align-items: center;
        margin-bottom: 10px;
    }
    .material-thumbnail {
        width: 100px;
        height: 100px;
        object-fit: cover;
        margin-right: 10px;
    }
    .stButton > button {
        background-color: #4CAF50;
        color: white;
        border-radius: 5px;
    }
    </style>
""", unsafe_allow_html=True)

def main():
    st.title("Reel Poster App")
    
    # 2列レイアウト
    col1, col2 = st.columns([2, 1])
    
    # 素材リスト（左側）
    with col1:
        st.subheader("素材リスト")
        materials = _refresh_materials()
        if materials:
            for material in materials:
                with st.container():
                    st.markdown('<div class="material-row">', unsafe_allow_html=True)
                    if material["Thumbnail"]:
                        st.image(material["Thumbnail"], caption=material["File Name"], use_column_width=False, width=100)
                    else:
                        st.write(f"サムネイルなし: {material['File Name']}")
                    col_comment, col_action = st.columns([3, 1])
                    with col_comment:
                        comment_key = f"{material['File Name']}_comment"
                        comment = st.text_input("コメント", value=material["Comment"], key=comment_key)
                        st.session_state[comment_key] = comment  # 入力値を保存
                    with col_action:
                        if st.button("削除", key=f"delete_{material['File Name']}"):
                            os.remove(os.path.join(os.getenv("PERSISTENT_DIR", "./"), "overlay_input", material["File Name"]))
                            if material["Thumbnail"] and os.path.exists(material["Thumbnail"]):
                                os.remove(material["Thumbnail"])
                            st.success(f"{material['File Name']} を削除しました")
                            st.rerun()
        else:
            st.write("素材がありません")
    
    # 素材アップロード（右側）
    with col2:
        st.subheader("素材アップロード")
        with st.container():
            st.markdown('<div class="upload-box">ドラッグ＆ドロップでアップロード</div>', unsafe_allow_html=True)
            uploaded_files = st.file_uploader(
                "ファイルを選択（200MBまで）",
                accept_multiple_files=True,
                type=[ext[1:] for ext in SUPPORTED_EXTS],
            )
            if uploaded_files:
                material_dir = os.path.join(os.getenv("PERSISTENT_DIR", "./"), "overlay_input")
                for file in uploaded_files:
                    with open(os.path.join(material_dir, file.name), "wb") as f:
                        f.write(file.getbuffer())
                    st.success(f"{file.name} をアップロードしました")
                st.rerun()

if __name__ == "__main__":
    main()
