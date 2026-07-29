import os
import fitz

def pdf_to_images(pdf_path: str, save_dir: str, dpi: int = 150):
    """
    PDF を PNG 画像に変換して save_dir に保存する。
    --------------------------------------------------------------------
    pdf_path : 変換するPDFファイルのパス
    save_dir : PNGを保存するディレクトリ
    dpi      : 画像解像度
    --------------------------------------------------------------------
    戻り値 : 生成したPNGファイルのパス一覧（リスト）
    """
    # 出力フォルダが無ければ作成
    os.makedirs(save_dir, exist_ok=True)

    # PDF読み込み
    pdf = fitz.open(pdf_path)
    out_files = []

    for i, page in enumerate(pdf):
        pix = page.get_pixmap(dpi=dpi)
        out_path = os.path.join(save_dir, f"{i+1:03}.png")
        pix.save(out_path)

        out_files.append(out_path)
        print(f"[OK] save {out_path}  ({pix.width}x{pix.height})")

    pdf.close()
    return out_files
