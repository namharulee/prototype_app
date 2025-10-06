# Use official Python 3.12 slim image (Render-compatible)
FROM python:3.12-slim

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

# Install system-level dependencies needed by OCR and OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the app into container
COPY . .

# Upgrade pip and install all Python dependencies
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Expose Render port (Render sets PORT automatically)
ENV PORT=10000
EXPOSE 10000

# Start FastAPI with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
