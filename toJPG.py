from PIL import Image


def resize_image(input_path, output_path, width=None, height=None, quality=95):
    """
    调整图片尺寸
    :param input_path: 输入图片路径
    :param output_path: 输出图片路径
    :param width: 目标宽度（像素）
    :param height: 目标高度（像素）
    :param quality: 输出图片质量（1-100）
    """
    try:
        # 打开图片
        with Image.open(input_path) as img:
            # 如果只指定了宽度或高度，按比例缩放
            if width and not height:
                height = int(img.height * width / img.width)
            elif height and not width:
                width = int(img.width * height / img.height)
            elif not width and not height:
                raise ValueError("必须指定宽度或高度")

            # 调整尺寸
            resized_img = img.resize((width, height), Image.Resampling.LANCZOS)

            # 保存图片
            resized_img.save(output_path, quality=quality)
            print(f"图片尺寸已修改：{img.size} -> {resized_img.size}")
            print(f"图片已保存至：{output_path}")

    except Exception as e:
        print(f"错误：{e}")


# 使用示例
if __name__ == "__main__":
    # 按指定宽度和高度调整
    resize_image("1.jpg", "output.jpg", width=2246, height=1321)
