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

# 3. Argumentos de construcción
ARG PROXY_URL
ARG CERT_PATH

# 4. Gestión del Certificado MITM (FORMA CORRECTA)
# Copiamos el cert a temporal
COPY ${CERT_PATH} /tmp/proxy-cert-source


# 4. Gestión del Certificado MITM con Conversión Automática
COPY ${CERT_PATH} /tmp/proxy-cert-source

# Intentamos tratarlo como DER (binario); si falla (||), lo copiamos tal cual (PEM)
RUN openssl x509 -inform DER -in /tmp/proxy-cert-source -out /usr/local/share/ca-certificates/proxy-ca.crt 2>/dev/null || \
    cp /tmp/proxy-cert-source /usr/local/share/ca-certificates/proxy-ca.crt

# Limpieza y permisos
RUN rm /tmp/proxy-cert-source && \
    chmod 644 /usr/local/share/ca-certificates/proxy-ca.crt && \
    update-ca-certificates



# 5. Volvemos al usuario airflow
USER airflow

# 6. Variables de proxy
ENV http_proxy=$PROXY_URL
ENV https_proxy=$PROXY_URL
ENV HTTP_PROXY=$PROXY_URL
ENV HTTPS_PROXY=$PROXY_URL

# 7. Python usará el trust store del sistema
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# 8. Instalación de dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 9. Código del proyecto
COPY --chown=airflow:root . /opt/airflow/project
RUN pip install --no-cache-dir /opt/airflow/project

ENV PYTHONPATH="/opt/airflow/project/src"
