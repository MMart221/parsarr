FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parsarr/ ./parsarr/

ENV PYTHONUNBUFFERED=1
ENV PARSARR_CONFIG=/config/config.yaml

EXPOSE 8080

ENTRYPOINT ["python", "-m", "parsarr.main"]
CMD ["serve"]
