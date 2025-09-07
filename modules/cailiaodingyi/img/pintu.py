import os

from PIL import Image

def concat_half(img1_path, img2_path, output_path):
    # 打开两张图
    img1 = Image.open(img1_path)
    img2 = Image.open(img2_path)

    # 以第一张为基准尺寸
    base_width, base_height = img1.size

    # 每张图占一半高度
    half_height = base_height // 2

    # 分别缩放两张图到 (base_width, half_height)
    img1_resized = img1.resize((base_width, half_height), Image.LANCZOS)
    img2_resized = img2.resize((base_width, base_height - half_height), Image.LANCZOS)

    # 新图（和第一张一样大小）
    new_img = Image.new("RGB", (base_width, base_height), (255, 255, 255))

    # 粘贴两半
    new_img.paste(img1_resized, (0, 0))
    new_img.paste(img2_resized, (0, half_height))

    # 保存
    new_img.save(output_path)
    print(f"✅ 拼接：{os.path.basename(img1_path)} + {os.path.basename(img2_path)} → {os.path.basename(output_path)}")

# 示例
def batch_concat():
    # 当前目录
    cur_dir = os.getcwd()

    # 基准拼接图片（凸密封面.jpg）
    base_img_name = "平密封面有覆层.jpg"
    base_img_path = os.path.join(cur_dir, base_img_name)

    if not os.path.exists(base_img_path):
        print(f"❌ 没找到 {base_img_name}")
        return

    # 遍历当前目录下的文件
    for fname in os.listdir(cur_dir):
        # 筛选条件：文件名包含“法兰”和“无覆层”
        if "法兰" in fname and "有覆层" in fname and fname.lower().endswith((".jpg", ".png", ".jpeg")):
            img1_path = os.path.join(cur_dir, fname)

            # 输出文件名：原文件名 + "-凸密封面（无覆层）.jpg"
            name, ext = os.path.splitext(fname)
            output_name = f"{name}-平密封面（有覆层）{ext}"
            output_path = os.path.join(cur_dir, output_name)

            # 拼接
            concat_half(img1_path, base_img_path, output_path)
batch_concat()