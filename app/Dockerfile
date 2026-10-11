FROM node:24.11.1-bookworm-slim
ENV NODE_ENV=production
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --chown=node:node app.js server.js ./
COPY --chown=node:node public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
