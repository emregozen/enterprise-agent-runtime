FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production \
    PORT=8842 \
    HOME=/tmp \
    STATIC_ROOT=/app/dist
RUN mkdir -p /tmp \
    && chgrp -R 0 /app /tmp \
    && chmod -R g=u /app /tmp
COPY --from=build --chown=1001:0 /app/dist ./dist
COPY --chown=1001:0 server.mjs ./server.mjs
USER 1001
EXPOSE 8842
CMD ["node", "server.mjs"]
