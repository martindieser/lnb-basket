<h1>Diseño del Pipeline de Datos</h1>

<h3>Tabla de Contenidos</h2>

- [Visión general](#visión-general)
- [Cómo fluyen los datos](#cómo-fluyen-los-datos)
- [Identificadores y Almacenamiento](#identificadores-y-almacenamiento)
- [Capa Bronze](#bronze)
- [Capa Silver](#silver)
- [Capa Gold](#gold)
- [Estadísticas que se miden para cada Jugador](#stats)
- [Deployment](#deployment)
- [TODO](#todo)


<h2 id="vision-general">Visión general</h2>

El pipeline extrae datos de partidos de básquetbol del sitio de la **CABB** (Confederación Argentina de Básquetbol) y los transforma volumenes de forma **batch** en un modelo analítico que permite responder preguntas sobre rendimiento de jugadores, lineups y estadísticas por partido.

Está organizado en tres capas: **Bronze**, **Silver** y **Gold** siguiendo una arquitectura Medallion. La idea central es que cada capa tiene una responsabilidad bien definida y puede ser re-ejecutada o modificada sin romper las demás. Si mañana la CABB cambia el formato de su web, solo se toca el código de la primera capa; el resto del pipeline sigue igual.
El pipeline garantiza que el resultado final sea el mismo sin importar cuántas veces se ejecute sobre los mismos datos. Esto se logra mediante una lógica de **Upsert** en la carga de cada ETL. Si un proceso de Prefect falla a mitad de camino, la siguiente ejecución retome el trabajo pendiente de forma segura y sin duplicar información.


<h2 id="cómo-fluyen-los-datos">Cómo fluyen los datos</h2>

<div align="center">
  <img src="/docs/general.jpg" alt="Diagrama de flujo" width="600">
</div>

El pipeline corre de punta a punta orquestado con **Prefect**: cada capa es conectada por un ETL que es un flow separado que se dispara cuando el anterior termina exitosamente. El almacenamiento se gestiona en el mismo bucket organizado en carpetas según la capa:

<div align="center">
  <table>
    <thead>
      <tr><th>Carpeta</th><th>Descripción</th><th>Formato</th></tr>
    </thead>
    <tbody>
      <tr><td><code>/raw/</code></td><td>Capa Bronze</td><td>JSON</td></tr>
      <tr><td><code>/curated/</code></td><td>Capa Silver</td><td>Parquet</td></tr>
      <tr><td><code>/analytics/</code></td><td>Capa Gold</td><td>Parquet</td></tr>
    </tbody>
  </table>
</div>

Silver y Gold usan Parquet porque el esquema ya está definido y las consultas son columnares optimizado para analiticas. Parquet comprime bien datos tabulares y es compatible con cualquier herramienta del ecosistema (DuckDB, Polars, Spark, Athena). Raw usa JSON para preservar fidelidad total a la fuente: si el formato de la CABB cambia o hay que reprocesar, el dato original está intacto.


<h2 id="identificadores-y-almacenamiento">Identificadores y Almacenamiento</h2>

El pipeline utiliza identificadores calculados y particionado en S3 para desacoplar el sistema de los proveedores y garantizar idempotencia en las cargas.

<h3>Identificadores</h3>

<div align="center">
  <table>
    <thead>
      <tr><th>Identificador</th><th>Regla</th><th>Capa</th><th>Descripción</th></tr>
    </thead>
    <tbody>
      <tr>
        <td><code>season_id</code></td>
        <td><code>liganacional{año_inicio}{año_fin}_basketball</code></td>
        <td>Bronze</td>
        <td>Corte en Agosto (mes 8). Si la fecha es &ge; 8, corresponde al año de inicio y siguiente (ej: <code>liganacional20232024_basketball</code>).</td>
      </tr>
      <tr>
        <td><code>cat_id</code></td>
        <td>Consulta en API</td>
        <td>Bronze</td>
        <td>Resuelve en el servidor de CABB la categoría según la liga y el <code>season_id</code>.</td>
      </tr>
      <tr>
        <td><code>match_id</code></td>
        <td><code>UUIDv5(MATCH_{YYYYMMDD}_{LOCAL}_{VISITANTE})</code></td>
        <td>Silver</td>
        <td>Generado a partir de nombres de equipos y fecha.</td>
      </tr>
      <tr>
        <td><code>team_id</code> / <code>player_id</code></td>
        <td><code>UUIDv5(TEAM_{NOMBRE})</code> / <code>UUIDv5(PLAYER_{NOMBRE})</code></td>
        <td>Silver</td>
        <td>Generado sobre el texto normalizado (sin tildes ni caracteres especiales).</td>
      </tr>
      <tr>
        <td><code>pbp_uuid</code></td>
        <td><code>UUIDv5({match_id}_{period}_{clk}_{seq}_{event_type})</code></td>
        <td>Silver</td>
        <td>Clave primaria para eventos de juego según partido, período, reloj, secuencia y tipo de evento.</td>
      </tr>
    </tbody>
  </table>
</div>

Los identificadores en Silver se generan con <code>uuid.uuid5</code> bajo el namespace <code>basketball.etl.system</code>. Ante los mismos datos de entrada se produce el mismo hash, permitiendo reprocesar datos sin duplicar registros.

<h3>Almacenamiento en S3</h3>

El almacenamiento se organiza en S3 según la capa:

<ul>
  <li><b>Capa Bronze (JSON):</b>
    <ul>
      <li>Partidos finalizados: <code>raw/{tipo_dato}_{season_id}/{match_id}.json</code> (donde <code>tipo_dato</code> es <code>pbp</code>, <code>agg_by_player</code> o <code>agg_by_team</code>). Permite verificar existencia en S3 por temporada y descargar registros faltantes.</li>
      <li>Partidos futuros: <code>raw/upcoming/{match_id}.json</code>. Se sobrescribe en cada ejecución con los partidos no disputados.</li>
      <li>Perfiles de sesión: <code>raw/profiles/{profile_id}.json</code>. Contiene estado y tokens de sesión para el scraping.</li>
    </ul>
  </li>
  <li><b>Capas Silver y Gold (Parquet):</b>
    <ul>
      <li>Archivos en formato Parquet bajo <code>curated/</code> (Silver) y <code>analytics/</code> (Gold).</li>
      <li>La escritura ejecuta Upsert: lee el archivo en S3, realiza merge con los registros entrantes mediante claves primarias y sobrescribe el archivo resultante.</li>
    </ul>
  </li>
</ul>


<h2 id="bronze">Capa Bronze</h2>
La capa Bronze es el archivo fiel de todo lo que viene de la fuente. No se transforma nada: si la CABB devuelve un campo con formato raro o un valor nulo inesperado, eso se guarda tal cual. Esto permite volver a reprocesar cualquier dato histórico sin tener que hacer scraping de nuevo.

Los datos de las consultas a la API de CABB se almacenan en formato JSON siguiendo el esquema: `raw/{tipo_dato}_{competicion}/{match_id}.json`

Los tipos de datos recolectados son:
-  `pbp` (Play-by-Play)
- `agg_by_player` (Estadísticas agregadas por jugador)
- `agg_by_team` (Comparativa de equipos).

El sistema utiliza un sistema de **IDs internos** (ej: `liga-nacional_basketball`) para desacoplarse de los IDs dinámicos de la API de CABB. Durante la ejecución, el scraper mapea estos identificadores internos con las categorías activas en el servidor mediante búsquedas semánticas. También para garantizar la persistencia del acceso, el scraper implementa un sistema de **sesiones rotativas**. Cada perfil representa un "dispositivo virtual" registrado con su propia clave de acceso. Estos perfiles se almacenan en `raw/profiles/` y son seleccionados aleatoriamente en cada corrida para distribuir la carga y minimizar el riesgo de bloqueos.

<h2 id="silver">Capa Silver</h2>
<div align="center">
  <img src="/docs/silver.jpg" alt="Modelado de datos: Normlización" width="600">
</div>

Se toman los datos crudos de Bronze y los normaliza separando las entidades principales en tablas relacionales con tipos correctos, sin duplicados y con claves foráneas explícitas. Es la capa que cualquier analista puede consultar directamente si quiere algo que Gold no tiene.

Puntos a considerar:
- No procesamos toda la historia en cada ejecución. El componente de extracción mantiene un registro de estado (`processed_keys.json`) en S3 que actúa como un checkpoint. En cada corrida, el flujo identifica y procesa únicamente los archivos nuevos. La única excepción es la carpeta `upcoming`, que se refresca íntegramente en cada ciclo para garantizar que la información de partidos futuros (horarios, estados) esté siempre actualizada hasta que se conviertan en resultados finales.

- **`past_matches` y `upcoming_matches` son tablas separadas** a propósito. Los partidos futuros no tienen puntos ni resultado; si los mezcláramos con los históricos, todas las consultas sobre resultados tendrían que filtrar NULLs estructurales. Separarlos hace que cada tabla tenga semántica clara. Cuando un partido termina, el ETL lo mueve de `upcoming` a `past`.

- `player_id` es nullable porque hay eventos que no corresponden a un jugador puntual.

<h2 id="gold">Capa Gold</h2>
<div align="center">
  <img src="/docs/gold.jpg" alt="Diagrama de flujo" width="600">
</div>

Se usan conceptos de modelado dimensional para optimizar el modelo relacional de la capa Silver para consultas de analitica OLAP. En este modelado existen dos tipos de tablas: **hechos**, que contiene eventos o transacciones que se quieren medir con la analitica y **dimensiones** que describen el contexto de los hechos. 
La granularidad de la tabla de hechos es a nivel stint por jugador: un intervalo de tiempo durante el cual un grupo de cinco jugadores estuvo en cancha sin cambios. Al agregar por `match_id` da las estadísticas de partido; agregar por `player_id` da el rendimiento histórico del jugador.
Luego alrededor de la tabla de hechos se construyen las dimensiones de equipo, partido, jugador, stint.

También, `dim_match` agrega un campo `result` que no existe en Silver, derivado de comparar `home_pts` y `away_pts`. Es un campo de conveniencia para no tener que calcularlo en cada consulta.

<h3 id="stats">Estadísticas que se miden para cada Jugador</h3>

<div align="center">
  <table>
    <thead>
      <tr><th>Campo</th><th>Descripción</th></tr>
    </thead>
    <tbody>
      <tr><td><code>pts</code></td><td>Puntos</td></tr>
      <tr><td><code>fg3m / fg3a</code></td><td>Triples convertidos / intentados</td></tr>
      <tr><td><code>fg2m / fg2a</code></td><td>Dobles convertidos / intentados</td></tr>
      <tr><td><code>ftm / fta</code></td><td>Tiros libres convertidos / intentados</td></tr>
      <tr><td><code>orb / drb</code></td><td>Rebotes ofensivos / defensivos</td></tr>
      <tr><td><code>ast</code></td><td>Asistencias</td></tr>
      <tr><td><code>stl</code></td><td>Robos</td></tr>
      <tr><td><code>blk / ba</code></td><td>Tapones realizados / recibidos</td></tr>
      <tr><td><code>tov</code></td><td>Pérdidas</td></tr>
      <tr><td><code>pf</code></td><td>Faltas personales</td></tr>
      <tr><td><code>tout</code></td><td>Tiempos muertos solicitados</td></tr>
      <tr><td><code>tech / flg</code></td><td>Faltas técnicas / flagrantes</td></tr>
      <tr><td><code>ftrips</code></td><td>Pasos / viajes</td></tr>
    </tbody>
  </table>
</div>




<h2 id="deployment">Deployment</h2>

El pipeline se ejecuta de forma <b>Serverless</b> orquestado por Prefect Cloud sobre la infraestructura administrada (Managed Pool), sin necesidad de mantener servidores o workers dedicados.

<h3>Configuración de Secretos</h3>

Para el acceso a AWS S3, Prefect Cloud y el repositorio privado de extracción, se configuran los siguientes secretos en el repositorio 

<div align="center">
  <table>
    <thead>
      <tr><th>Nombre</th><th>Descripción</th></tr>
    </thead>
    <tbody>
      <tr><td><code>GIT_TOKEN</code></td><td>Personal Access Token con permisos de lectura para instalar la librería privada <code>cabb-client</code>.</td></tr>
      <tr><td><code>PREFECT_API_KEY</code></td><td>API Key de autenticación en Prefect Cloud.</td></tr>
      <tr><td><code>PREFECT_API_URL</code></td><td>URL del workspace de Prefect Cloud.</td></tr>
      <tr><td><code>S3_BUCKET_NAME</code></td><td>Nombre del bucket de AWS S3 donde se almacena el data warehouse.</td></tr>
      <tr><td><code>AWS_ACCESS_KEY_ID</code></td><td>Access Key ID de AWS IAM con permisos en S3.</td></tr>
      <tr><td><code>AWS_SECRET_ACCESS_KEY</code></td><td>Secret Access Key de AWS IAM.</td></tr>
      <tr><td><code>AWS_REGION</code></td><td>Región de AWS (ej: <code>us-east-1</code>).</td></tr>
      <tr><td><code>S3_RAW_PREFIX</code></td><td>Prefijo de la capa Bronze en S3 (<code>raw</code>).</td></tr>
      <tr><td><code>S3_CURATED_PREFIX</code></td><td>Prefijo de la capa Silver en S3 (<code>curated</code>).</td></tr>
      <tr><td><code>S3_ANALYTICS_PREFIX</code></td><td>Prefijo de la capa Gold en S3 (<code>analytics</code>).</td></tr>
    </tbody>
  </table>
</div>

<h3>Infraestructura en Prefect Cloud</h3>

El pool de ejecución requerido en Prefect Cloud es de tipo <b>Prefect Managed</b>:
1. En Prefect Cloud, ir a <b>Work Pools</b>.
2. Crear un pool seleccionando el tipo <b>Prefect Managed</b>.
3. Asignar el nombre <code>default-managed</code>.

Los secretos (credenciales de S3 y token de GitHub) se sincronizan automáticamente con Github Actions hacia Prefect Cloud.


<h2 id="todo">TODO</h2>
- Agregar diferentes fuentes de datos para enriquecer datos de jugadores ej: altura