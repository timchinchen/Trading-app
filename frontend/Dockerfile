# ---------- build ----------
# Chainguard node (dev variant) keeps npm available for `npm ci`/`npm run build`.
FROM cgr.dev/chainguard/node:latest-dev AS builder

WORKDIR /app

# Install deps first (cache-friendly)
COPY package.json package-lock.json ./
RUN npm ci

# Build-time configuration. With the two-port layout the browser talks
# directly to the backend, so VITE_API_URL must point at the host:port the
# user will actually hit (default for local dev: http://localhost:8000).
ARG VITE_API_URL=http://localhost:8000
ARG VITE_WS_URL=ws://localhost:8000
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_WS_URL=${VITE_WS_URL}

COPY . .
RUN npm run build

# ---------- serve ----------
# Chainguard nginx runs as non-root by default and serves on 8080.
FROM cgr.dev/chainguard/nginx:latest AS runtime

# SPA-friendly config: route every unknown path back to index.html
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD nginx -t
