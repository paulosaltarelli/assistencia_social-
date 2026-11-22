FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=pip_ca if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; pip install --no-cache-dir -r requirements.txt
COPY manage.py ./
COPY config/ ./config/
COPY atendimentos/ ./atendimentos/
COPY contas/ ./contas/
COPY cadastros/ ./cadastros/
COPY programas/ ./programas/
COPY financeiro/ ./financeiro/
COPY documentos/ ./documentos/
COPY relatorios/ ./relatorios/
COPY infra/migrate.sh ./infra/migrate.sh
RUN DJANGO_SECRET_KEY=build-only SOCIAL_DB_PASSWORD=build-only python manage.py collectstatic --noinput && chmod -R a+rX /app
USER 65534:65534
CMD ["gunicorn","--bind","0.0.0.0:8000","--workers","1","--no-control-socket","--error-logfile","-","config.wsgi"]
