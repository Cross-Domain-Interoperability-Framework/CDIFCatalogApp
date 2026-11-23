# The image Render builds (see render.yaml): the built web app and the server in one container.
# Build from the repository root:   docker build -f deploy/Dockerfile .
# For development use docker-compose.yml, which runs the Vite and reloading servers instead.
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server/app ./app
COPY server/converters ./converters
# The converters and the validation repository inside them are git submodules. Stop here, and
# say why, if the checkout came without them.
RUN test -f converters/validation/detect_conformance.py \
    || (echo "server/converters or its validation submodule is missing: fetch the git submodules recursively" && exit 1)
COPY --from=web /web/dist ./web
ENV WEB_DIR=/srv/web
# One container runs the harvest worker beside the server, because Render has no free background
# worker. Nothing restarts the worker if it stops; the next deploy or restart brings it back.
# PUBLIC_URL defaults to the address Render gives the service; PORT is set by Render.
CMD ["sh", "-c", "export PUBLIC_URL=${PUBLIC_URL:-$RENDER_EXTERNAL_URL}; python -m app.harvest.worker & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
