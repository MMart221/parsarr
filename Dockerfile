FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parsarr/ ./parsarr/

ENV PYTHONUNBUFFERED=1
ENV PARSARR_CONFIG=/config/config.yaml

LABEL org.opencontainers.image.source="https://github.com/MMart221/parsarr"
LABEL org.opencontainers.image.description="Media import preprocessor for the *arr stack"
LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"

EXPOSE 8080

ENTRYPOINT ["python", "-m", "parsarr.main"]
CMD ["serve"]
