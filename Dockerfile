# syntax=docker/dockerfile:1
# 1. Imagen base de Python ligera
FROM python:3.11-slim

# Directorio de trabajo
WORKDIR /app

# 2. Utilidades del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    git \
    ca-certificates \
    openssl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. Instalación de dependencias públicas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Instalación del paquete privado cabb-client de forma segura (sin filtrar token en el historial)
RUN --mount=type=secret,id=git_token \
    GIT_TOKEN=$(cat /run/secrets/git_token) && \
    pip install --no-cache-dir "git+https://x-access-token:${GIT_TOKEN}@github.com/martindieser/cabb-client.git"

# 5. Código del proyecto
COPY . .

# Variables de entorno
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# Comando por defecto: Iniciar un worker de Prefect
CMD ["prefect", "worker", "start", "--pool", "default-agent-pool"]
