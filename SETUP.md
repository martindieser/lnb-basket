# Guía de Configuración: Prefect Serverless & CI/CD

Esta guía detalla los pasos necesarios para configurar el entorno de producción para el scraper de la CABB utilizando **Prefect Cloud** y **GitHub Actions**.

## 1. Configuración de GitHub (Secrets)

Para que el despliegue automático funcione, ve a tu repositorio en GitHub: **Settings > Secrets and variables > Actions** y agrega los siguientes "Repository Secrets":

| Nombre | Descripción |
| :--- | :--- |
| `PREFECT_API_KEY` | Tu API Key de Prefect Cloud (empieza con `pnu_`). |
| `PREFECT_API_URL` | La URL de tu workspace de Prefect Cloud. |

## 2. Configuración de Prefect Cloud

### A. Crear el Work Pool (Infraestructura)
Antes del primer despliegue, debes crear el lugar donde correrá el código:
1. En Prefect Cloud, ve a **Work Pools**.
2. Haz clic en **Create Work Pool**.
3. Selecciona el tipo **Prefect Managed**.
4. Nombre del pool: `default-managed`.
5. Haz clic en **Create**.

### B. Bloques (Blocks) - Acceso al Repositorio
Para clonar tu repositorio privado:
1. En Prefect Cloud, ve a **Blocks** > **+ Add Block**.
2. Selecciona **Secret**.
3. **Block Name:** `github-token`
4. **Value:** Tu GitHub Personal Access Token (PAT) con permisos de lectura.

### C. Variables - Configuración de la App
Ve a **Variables** en el menú lateral y agrega las siguientes para que el flujo las use en tiempo de ejecución:

| Variable | Valor sugerido / Ejemplo |
| :--- | :--- |
| `AWS_ACCESS_KEY_ID` | Tu Access Key de AWS. |
| `AWS_SECRET_ACCESS_KEY` | Tu Secret Key de AWS. |
| `AWS_REGION` | `us-east-1` |
| `S3_BUCKET_NAME` | `lbn-basket` |
| `S3_RAW_PREFIX` | `raw` |
| `S3_CURATED_PREFIX` | `curated` |

## 3. Despliegue (CI/CD)

Una vez configurados los secretos en GitHub, el despliegue es automático:

1. Haz un `push` a la rama `migrate-to-prefect`.
2. GitHub Actions ejecutará el workflow "Deploy to Prefect Cloud".
3. Al terminar, verás un nuevo "Deployment" llamado `daily-cabb-etl` en tu dashboard de Prefect Cloud.

## 4. Ejecución y Monitoreo

- **Schedule:** El flujo está programado para ejecutarse diariamente a las 00:00 UTC.
- **Manual:** Puedes disparar una ejecución manual desde el botón "Run" en la página del Deployment en Prefect Cloud.
- **Logs:** Todos los logs de scraping y procesamiento aparecerán en tiempo real en la pestaña "Runs" de Prefect.
