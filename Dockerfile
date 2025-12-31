FROM python:3.12-slim

WORKDIR /app

# Install deps
RUN pip install --no-cache-dir tmdbsimple pyarr

# Copy script
COPY main.py /app/main.py
RUN chmod +x /app/main.py

# Non-root (optional but recommended)
RUN useradd -u 10001 -m appuser
USER 10001

ENTRYPOINT ["/app/main.py"]