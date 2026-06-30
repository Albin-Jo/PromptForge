# syntax=docker/dockerfile:1
#
# Multi-stage build for the PromptForge UI.
#   build    — installs deps and runs `npm run build` (tsc + Vite) to produce dist/
#   runtime  — nginx:alpine serving the static bundle; no Node at runtime
#
# Build context is ./ui (set in docker-compose.yml), so paths below are relative
# to ui/.

# ---- Build -----------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Dependency layer first — only the manifests, so this layer is cached until
# package.json or package-lock.json changes, not on every source edit.
COPY package.json package-lock.json ./
RUN npm ci

# Source layer — everything else (src/, index.html, vite.config.ts, tsconfig*, …)
COPY . .

# VITE_API_BASE_URL is baked into the JS bundle at build time (import.meta.env).
# The default is the API's published host port. The browser fetches this URL
# directly, so it must be reachable from the user's machine — localhost:8001 is
# correct for local compose where the api publishes `ports: "8001:8000"`.
# Override this build arg when deploying to a real URL, e.g.:
#   docker build --build-arg VITE_API_BASE_URL=https://api.example.com .
ARG VITE_API_BASE_URL=http://localhost:8001
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ---- Runtime ---------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# SPA routing config: fall back to index.html so react-router handles deep routes,
# and cache hashed assets aggressively (see nginx.conf).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static bundle from the build stage.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
