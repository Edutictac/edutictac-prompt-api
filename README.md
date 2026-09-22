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
