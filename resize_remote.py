from PIL import Image

def resize_image(path, out_path, size):
    try:
        img = Image.open(path)
        img = img.resize(size, Image.LANCZOS)
        img.save(out_path)
        print(f"Resized {path} to {size} -> {out_path}")
    except Exception as e:
        print(f"Error resizing {path}: {e}")

resize_image('/home/banorz/bootlogo.png', '/home/banorz/bootlogo.png', (800, 480))
resize_image('/home/banorz/recorder/bg.png', '/home/banorz/recorder/bg.png', (800, 480))
