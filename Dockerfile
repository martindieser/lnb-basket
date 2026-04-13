# 1. Imagen base de Airflow
FROM apache/airflow:3.1.6-python3.11

USER root

# 2. Utilidades del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    git \
    ca-certificates \
    openssl \
    && apt-get clean

USER airflow

# 3. Instalación de dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Código del proyecto
COPY --chown=airflow:root . /opt/airflow/project
RUN pip install --no-cache-dir /opt/airflow/project

ENV PYTHONPATH="/opt/airflow/project/src"
