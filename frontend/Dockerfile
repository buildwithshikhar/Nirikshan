# Nirikshan frontend image: static Vite build served by unprivileged nginx, which also proxies
# /api and /health to the backend. Build context = repository root:
#   docker build -f frontend/Dockerfile -t nirikshan-offline-frontend .
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY docs/ /docs/
# Backend base URL baked into the bundle. Empty (default) = same origin: nginx proxies /api to the backend.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
USER 101
