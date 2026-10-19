FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY detect.py .
# Le modèle entraîné est monté en volume (voir docker-compose) ou copié ici :
# COPY detector_model.joblib .

CMD ["python", "-u", "detect.py"]
