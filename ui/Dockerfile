FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ARG CONTROL_PLANE_URL=http://control-plane.agent-runtime.svc:8841
ENV CONTROL_PLANE_URL=$CONTROL_PLANE_URL
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8842 \
    HOSTNAME=0.0.0.0 \
    HOME=/tmp
RUN mkdir -p /tmp /app/.next/cache \
    && chgrp -R 0 /app /tmp \
    && chmod -R g=u /app /tmp
COPY --from=build --chown=1001:0 /app/public ./public
COPY --from=build --chown=1001:0 /app/.next/standalone ./
COPY --from=build --chown=1001:0 /app/.next/static ./.next/static
USER 1001
EXPOSE 8842
CMD ["node", "server.js"]
