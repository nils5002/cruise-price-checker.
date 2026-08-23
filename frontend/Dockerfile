# --- build stage -----------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# package-lock.json ist eingecheckt -> reproduzierbarer Build mit "npm ci".
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

# VITE_API_BASE lets you point the UI at a different API prefix if needed.
ARG VITE_API_BASE=/api
ARG VITE_BASE_PATH=/
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_BASE_PATH=$VITE_BASE_PATH
RUN npm run build

# --- runtime stage ---------------------------------------------------------
FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
