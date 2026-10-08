FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
ARG INSTALL_ML=true
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements.txt README.md alembic.ini config.yaml ./
RUN python -c "import tomllib,subprocess; p=tomllib.load(open('pyproject.toml','rb'))['project']; subprocess.check_call(['pip','install',*p['dependencies']])" \
    && if [ "$INSTALL_ML" = "true" ]; then pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install 'sentence-transformers>=3.4,<6'; fi \
    && useradd --create-home --uid 10001 lakshya \
    && mkdir -p /app/data /app/output /app/config-store && chown -R lakshya:lakshya /app
COPY --chown=lakshya:lakshya backend ./backend
RUN pip install --no-deps .
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium
USER lakshya
EXPOSE 8000
CMD ["sh", "-c", "test -f \"$LAKSHYA_CONFIG\" || cp /app/config.yaml \"$LAKSHYA_CONFIG\"; lakshya init-db && lakshya serve --host 0.0.0.0 --port 8000"]
