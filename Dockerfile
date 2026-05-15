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
    && apt-get clean

# 3. Instalación de dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Código del proyecto
COPY . .
# Se evita instalar el paquete local siguiendo las indicaciones del TODO.md

# Variables de entorno
# Establecemos PYTHONPATH en /app para que las importaciones 'from src.xxx' funcionen correctamente
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# Comando por defecto: Iniciar un worker de Prefect
# Nota: Requiere configurar PREFECT_API_URL y PREFECT_API_KEY en el entorno
CMD ["prefect", "worker", "start", "--pool", "default-agent-pool"]
