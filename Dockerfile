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

# 4. Instalación del paquete privado cabb-client
ARG GITHUB_TOKEN
RUN pip install --no-cache-dir "git+https://${GITHUB_TOKEN}@github.com/martindieser/cabb-client.git"

# 5. Código del proyecto
COPY . .

# Variables de entorno
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# Comando por defecto: Iniciar un worker de Prefect
CMD ["prefect", "worker", "start", "--pool", "default-agent-pool"]
