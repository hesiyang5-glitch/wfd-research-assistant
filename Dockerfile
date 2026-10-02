# WFD Coding Assistant — container image for cloud hosting (e.g. Render).
FROM python:3.11-slim
# Tesseract gives OCR for scanned PDF pages.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Listen on all interfaces inside the container; login is required (the server refuses to start without WFD_PASSWORD).
ENV WFD_HOST=0.0.0.0 \
    WFD_DATA_DIR=/var/data \
    WFD_TRUST_PROXY=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1
EXPOSE 8765
CMD ["python", "-m", "app.server"]
