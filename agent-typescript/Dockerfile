FROM node:20-slim AS build

WORKDIR /app

# Install dependencies first so they cache independently of source changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:20-slim

WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY --from=build /app/dist ./dist

ENV TOKEN_STORE_PATH=/app/data/mcp-auth.json

EXPOSE 3000

CMD ["node", "dist/main.js"]
