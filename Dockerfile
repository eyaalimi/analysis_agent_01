# ── AWS Lambda Python 3.11 container image ────────────────────────────────────
FROM public.ecr.aws/lambda/python:3.11

# Install system dependencies required by pytesseract (OCR)
# and pdfplumber (PDF rendering)
RUN dnf install -y \
    tesseract \
    tesseract-langpack-fra \
    tesseract-langpack-eng \
    poppler-utils \
    && dnf clean all

# Copy and install Python dependencies first (Docker layer cache)
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy application code
COPY agents/         ${LAMBDA_TASK_ROOT}/agents/
COPY email_gateway/  ${LAMBDA_TASK_ROOT}/email_gateway/
COPY config.py       ${LAMBDA_TASK_ROOT}/
COPY logger.py       ${LAMBDA_TASK_ROOT}/
COPY lambda_handler.py ${LAMBDA_TASK_ROOT}/

# Lambda entry point: file.function
CMD ["lambda_handler.handler"]
