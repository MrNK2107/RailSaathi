# RailSaathi AI frontend: Vite build served by nginx, which also reverse-proxies the API so the
# browser only ever talks to one origin (no CORS, no credentials handling).
# Build:  docker build -t railsaathi-frontend ./frontend
# Run:    docker run --rm -p 8080:8080 -e BACKEND_URL=http://host.docker.internal:8000 railsaathi-frontend

FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Same-origin API: the client defaults to relative /api paths, so no base URL is baked in.
ENV VITE_API_BASE_URL=""
# Hidden source maps and the Vite manifest are build artefacts, not something to serve to browsers.
RUN npm run build && rm -rf dist/.vite && find dist -name '*.map' -delete


FROM nginx:1.27-alpine AS runtime

# The official image renders /etc/nginx/templates/*.template with envsubst at start-up.
ENV PORT=8080 \
    BACKEND_URL=http://127.0.0.1:8000 \
    NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx/conf.d

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY nginx/15-resolver.envsh /docker-entrypoint.d/15-resolver.envsh
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${PORT}/healthz" || exit 1
