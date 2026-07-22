from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


def preprocess_image(input_path: Path, output_path: Path) -> Path:
    image = ImageOps.exif_transpose(Image.open(input_path)).convert("RGB")
    array = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21)
    enhanced = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(gray)
    cv2.imwrite(str(output_path), enhanced)
    return output_path

