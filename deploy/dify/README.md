# Dify 1.15.0 Local Overlay

The full Dify source tree is intentionally not vendored in this repository.
Clone the official release first:

```bash
git clone --branch 1.15.0 --depth 1 https://github.com/langgenius/dify.git dify-self-host
cd dify-self-host/docker
cp .env.example .env
```

For this project, configure the following non-secret ports in Dify's `.env`:

```dotenv
EXPOSE_NGINX_PORT=18080
EXPOSE_NGINX_SSL_PORT=18443
EXPOSE_PLUGIN_DEBUGGING_PORT=15003
```

Choose strong, unique values for every password and secret in that file.

Copy this overlay into Dify's Docker directory and start the stack:

```bash
cp ../../deploy/dify/Dockerfile.api-jieba .
cp ../../deploy/dify/docker-compose.smart-business.yaml .
cp ../../deploy/dify/rebuild-local-api.sh .
chmod +x rebuild-local-api.sh

docker compose \
  -f docker-compose.yaml \
  -f docker-compose.smart-business.yaml \
  --profile collaboration \
  up -d --build
```

The overlay does two project-specific things:

1. Adds `jieba==0.42.1` to Dify API/worker images so Economy keyword search
   works with Dify 1.15.0.
2. Mounts shared storage into `api_websocket`, which is required by the file
   upload flow used in this local deployment.

After rebuilding the Python services, run `./rebuild-local-api.sh`; it refreshes
Nginx so it does not retain an old API container address.

Do not commit `dify-self-host/docker/.env`, Dify service API keys, Dataset IDs,
or generated volume contents.
