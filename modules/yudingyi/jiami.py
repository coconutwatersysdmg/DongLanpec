import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ==== 配置 ====
IMG_DIR = "static/pdf_images"       # 原始 JPG 图片目录
ENC_DIR = "encrypted_images"        # 加密后存放目录
KEY = b"1234567890abcdef"  # 16 字节，AES-128
IV = b"abcdef1234567890"   # 16 字节，AES-CBC 必须 16 字节

os.makedirs(ENC_DIR, exist_ok=True)

def encrypt_file(input_path, output_path):
    with open(input_path, "rb") as f:
        data = f.read()
    cipher = AES.new(KEY, AES.MODE_CBC, IV)
    enc_data = cipher.encrypt(pad(data, AES.block_size))
    with open(output_path, "wb") as f:
        f.write(enc_data)

# 遍历原始图片加密
for filename in os.listdir(IMG_DIR):
    if filename.lower().endswith(".jpg"):
        in_path = os.path.join(IMG_DIR, filename)
        out_name = filename.replace(".jpg", ".enc")
        out_path = os.path.join(ENC_DIR, out_name)
        encrypt_file(in_path, out_path)
        print(f"加密完成: {filename} → {out_name}")

print("所有图片已加密完成！")
