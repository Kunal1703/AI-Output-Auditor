# AI Output Auditor — frontend image (Document 4, §2: Docker).
#
# Build with node, serve with nginx. The app is a static bundle after `vite
# build`, so shipping node into the runtime would ship a JavaScript runtime to
# serve files that no longer need one.

# --------------------------------------------------------------------------- #
# Stage 1 — build the bundle
# --------------------------------------------------------------------------- #
FROM node:20-alpine AS builder

WORKDIR /build

# Manifest first: a source edit should not re-run `npm ci`.
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# `npm run build` runs `tsc --noEmit` before vite, so a type error fails the
# image build rather than shipping. That is deliberate — the frontend's job is
# to render the frozen contracts, and a drift from them should stop the build.
RUN npm run build

# --------------------------------------------------------------------------- #
# Stage 2 — serve
# --------------------------------------------------------------------------- #
FROM nginx:1.27-alpine

LABEL org.opencontainers.image.title="AI Output Auditor — frontend"

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
