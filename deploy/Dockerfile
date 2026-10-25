FROM idootop/open-xiaoai-migpt@sha256:8cd399ec8e8164d9a4f56df6291791a8db6cc881b22d9be6284eea6e1a68595b
COPY deploy/bridge /app/bridge
COPY deploy/bridge/vendor/ws /app/bridge/node_modules/ws
COPY config /config
CMD ["node", "/app/bridge/index.mjs"]
