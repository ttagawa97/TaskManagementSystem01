FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip check
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app && mkdir -p /media && chown app:app /media
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["sh", "entrypoint.sh"]
