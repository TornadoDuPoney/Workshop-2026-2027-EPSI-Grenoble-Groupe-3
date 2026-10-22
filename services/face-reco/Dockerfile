FROM python:3.12-slim

# Dépendances système d'OpenCV (headless) + accès vidéo V4L + curl pour les modèles.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libsm6 libxext6 libxrender1 curl \
    && rm -rf /var/lib/apt/lists/*

# Modèles de reconnaissance faciale (OpenCV Zoo), téléchargés une fois au build.
RUN mkdir -p /models \
    && curl -fsSL -o /models/yunet.onnx \
       https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    && curl -fsSL -o /models/sface.onnx \
       https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
