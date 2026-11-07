# EduTicTac Prompt API

Backend privado para sincronizar la biblioteca de prompts de EduTicTac Prompt.
Usa Authentik mediante OIDC, conserva cada prompt aislado por usuario y deja la
PWA funcionando en modo offline con IndexedDB.

## Desarrollo

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
uvicorn app.main:app --reload --port 8012
```

La configuración se hace mediante variables de entorno. En local se puede usar
`PROMPT_DEV_USER` para probar la API sin Authentik; no debe configurarse en
producción.

## Endpoints

- `GET /api/auth/login`, `/callback`, `/logout`, `/me`
- `GET /api/prompts`
- `PUT /api/prompts/{id}`
- `DELETE /api/prompts/{id}`

El backend nunca acepta un `ownerId` enviado por el navegador: siempre usa la
identidad validada en la sesión OIDC.

## Sesión central de EduTicTac (fase 4)

Con `PROMPT_CENTRAL_SESSION_URL` y `PROMPT_APP_TOKEN`, la API valida la sesión
central de Commons en `GET /api/internal/session/resolve` (solo red interna,
127.0.0.1:8005) reenviando las cookies del navegador. El token de aplicación es
exclusivo del servidor y nunca se expone al cliente. Se usa el `sub` de
Authentik (`hashed_user_id`), el mismo en todos los proveedores, así que la
biblioteca existente conserva su propietario sin migración.

La sesión central tiene prioridad: si Commons dice «anónimo», no se recupera una
sesión local antigua. La sesión OIDC propia queda como respaldo únicamente si el
servicio central no responde (error de infraestructura) o en instalaciones sin
Commons. `GET /api/auth/me` devuelve `central: true` cuando esta modalidad está
activa.

## Skills (0.2.0)

La extensión `app/skills.py` reutiliza la sesión OIDC, SQLite y httpx existentes.
Añade biblioteca privada (`GET/PUT/DELETE /api/skills`), capacidades públicas sin
secretos (`GET /api/skills/capabilities`) e inferencia opcional autenticada
(`POST /api/skills/infer`). El frontend 0.15.0 usa estas rutas; las rutas de
prompts se conservan.

La migración de Skills es aditiva e idempotente al iniciar. Los SQL de referencia
están en `deploy/skills-up.sql` y `skills-down.sql`; el segundo es solo para una
reversión manual tras respaldo. El rollback habitual conserva la tabla y vuelve
al código anterior. La propiedad se deriva del `sub` autenticado; todas las
operaciones se filtran por usuario. PUT/POST/DELETE requieren Origin autorizado;
PUT/POST, JSON. La revisión evita sobrescrituras obsoletas (409).

No hay proveedor obligatorio. Por defecto `capabilities` devuelve cero
proveedores y la PWA sigue usando asistentes web (incluido Copilot M365). Para
habilitar un servicio Chat Completions compatible, configurar únicamente en el
EnvironmentFile protegido del servidor:

- `PROMPT_AI_BASE_URL`: raíz `/v1` del servicio autorizado por la administración.
- `PROMPT_AI_MODELS`: modelos permitidos, separados por comas.
- `PROMPT_AI_NAME`: nombre del proveedor mostrado a las personas usuarias.
- `PROMPT_AI_API_KEY`: opcional, si el servicio requiere autenticación; nunca en
  variables `VITE_`, repositorios, logs ni respuestas al cliente.

La inferencia requiere consentimiento, parámetros/definición válidos, contenido
revisado y modalidad de instrucciones. Solo se envía texto y política de sistema;
no se conceden herramientas ni scripts. El mensaje de usuario es exactamente la
petición preparada visible del navegador, tratada como contenido no confiable.
Se limita a una llamada concurrente y diez por minuto/usuario/proceso, 60 s,
4096 tokens de salida y respuestas acotadas. El proveedor se prueba con transporte
simulado; habilitarlo requiere prueba con el servicio real elegido. Los errores
no muestran mensajes ni cuerpos del proveedor.

Pruebas: `.venv/bin/pytest -q` (regresión de prompts, permisos, CORS/origen,
estructura, tamaño, conflictos, inferencia simulada y fallos).
