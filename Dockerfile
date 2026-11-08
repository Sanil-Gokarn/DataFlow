FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATAFLOW_PUBLIC=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8501
HEALTHCHECK CMD python -c "import os,urllib.request as u; u.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8501\")}/_stcore/health')" || exit 1

# Hosts like Railway and Render pass the port in $PORT.
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true"]
