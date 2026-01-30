import cv2
import numpy as np
import sqlite3

def preprocess_image_for_ocr(image, threshold, blur_ksize, contrast, resize_ratio, gaussian_blur_ksize, use_clahe):
    # 画像のリサイズ
    image = cv2.resize(image, (0, 0), fx=resize_ratio, fy=resize_ratio)

    # HSV に変換
    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # V（明度）チャネルを強調する
    v_channel = hsv_image[:, :, 2]
    v_channel = cv2.equalizeHist(v_channel)
    hsv_image[:, :, 2] = v_channel

    # HSV 画像を BGR に戻す
    image = cv2.cvtColor(hsv_image, cv2.COLOR_HSV2BGR)

    # ガウシアンブラーを使用してノイズを減らす
    if gaussian_blur_ksize > 0:
        image = cv2.GaussianBlur(image, (gaussian_blur_ksize, gaussian_blur_ksize), 0)

    # アダプティブ二値化
    _, binary_image = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY_INV)
    
    if use_clahe:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        binary_image = clahe.apply(binary_image)

    # 小さな穴を埋める
    kernel = np.ones((3, 3), np.uint8)
    binary_image = cv2.morphologyEx(binary_image, cv2.MORPH_CLOSE, kernel)

    return binary_image

def warmup_and_check_all_images():
    # 省略
