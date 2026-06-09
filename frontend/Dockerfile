FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_PLUGIN_AGENT_API=/plugin-agent-api
ENV VITE_PLUGIN_AGENT_API=$VITE_PLUGIN_AGENT_API

COPY package.json yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile

COPY index.html ./
COPY src ./src
RUN yarn build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
