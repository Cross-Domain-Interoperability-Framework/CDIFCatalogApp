# The image Render builds (see render.yaml): the built web app and the server in one container.
# Build from the repository root:   docker build -f deploy/Dockerfile .
# For development use docker-compose.yml, which runs the Vite and reloading servers instead.
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

# Render does not fetch git submodules, so the converters are fetched here, at the commit the
# server/converters submodule is pinned to, with the validation repository inside them. When the
# submodule moves, change this commit to match; CI fails if the two differ.
FROM alpine:3.20 AS converters
RUN apk add --no-cache git
ARG CONVERTERS_COMMIT=58fd83c976b6b3e987ef97a8278542753b70565a
WORKDIR /converters
RUN git init -q . \
    && git remote add origin https://github.com/Cross-Domain-Interoperability-Framework/converters.git \
    && git fetch -q --depth 1 origin "$CONVERTERS_COMMIT" \
    && git checkout -q FETCH_HEAD \
    && git submodule update -q --init --recursive --depth 1 \
    && test -f validation/detect_conformance.py \
    && rm -rf .git validation/.git

FROM python:3.12-slim
WORKDIR /srv
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server/app ./app
COPY --from=converters /converters ./converters
COPY --from=web /web/dist ./web
ENV WEB_DIR=/srv/web
# One container runs the harvest worker beside the server, because Render has no free background
# worker. Nothing restarts the worker if it stops; the next deploy or restart brings it back.
# PUBLIC_URL defaults to the address Render gives the service; PORT is set by Render.
CMD ["sh", "-c", "export PUBLIC_URL=${PUBLIC_URL:-$RENDER_EXTERNAL_URL}; python -m app.harvest.worker & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
