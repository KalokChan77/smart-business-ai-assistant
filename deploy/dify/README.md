# Dify 1.15.0 Local Overlay

The full Dify source tree is intentionally not vendored in this repository.
Clone the official release first:

```bash
git clone --branch 1.15.0 --depth 1 https://github.com/langgenius/dify.git dify-self-host
cd dify-self-host/docker
cp .env.example .env
```

Windows PowerShell uses the same repository, with native copy commands:

```powershell
git clone --branch 1.15.0 --depth 1 https://github.com/langgenius/dify.git dify-self-host
Set-Location dify-self-host\docker
Copy-Item .env.example .env
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

Windows PowerShell, run from the main project root:

```powershell
Copy-Item .\deploy\dify\Dockerfile.api-jieba .\dify-self-host\docker\
Copy-Item .\deploy\dify\docker-compose.smart-business.yaml .\dify-self-host\docker\
Copy-Item .\deploy\dify\rebuild-local-api.ps1 .\dify-self-host\docker\

Set-Location .\dify-self-host\docker
docker compose `
  -f docker-compose.yaml `
  -f docker-compose.smart-business.yaml `
  --profile collaboration `
  up -d --build
```

The overlay does two project-specific things:

1. Adds `jieba==0.42.1` to Dify API/worker images so Economy keyword search
   works with Dify 1.15.0.
2. Mounts shared storage into `api_websocket`, which is required by the file
   upload flow used in this local deployment.

After rebuilding the Python services, run `./rebuild-local-api.sh`; it refreshes
Nginx so it does not retain an old API container address.

Windows runs the equivalent command with
`powershell -ExecutionPolicy Bypass -File .\rebuild-local-api.ps1`.

Do not commit `dify-self-host/docker/.env`, Dify service API keys, Dataset IDs,
or generated volume contents.
