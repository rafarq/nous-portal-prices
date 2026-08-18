# Nous Portal Prices

Web estática con los precios por token del catálogo de **Nous Portal**
(modelos de OpenRouter), ordenable por precio y con comparador de modelos
anclados que persiste entre navegadores.

## Características

- ~260 modelos del catálogo de Nous Portal con precio **in/out por 1M tokens** y contexto
- Ordenación por Input / Output / Contexto / Nombre y búsqueda por texto
- **Comparador de anclados**: fija modelos con 📌, reordénalos (arrastrar o ▲/▼),
  ordénalos por precio (Manual/In/Out) — persiste entre navegadores
- Marcas de cambio al actualizar: ▲ subió / ▼ bajó (con %) / 🆕 nuevo
- Pantalla completa: sin zoom, scroll horizontal solo en la tabla

## Estructura

| Fichero | Función |
|---|---|
| `index.html` | La web (autocontenida, sin dependencias) |
| `prices.json` | Datos generados (modelos + precios + cambios) |
| `fetch_prices.py` | Genera `prices.json` desde el markdown del portal |
| `pin.php` | Endpoint GET/POST para guardar los anclados en `pins.json` |
| `config.js` / `config.php` | **Local, no versionados**: token de escritura de pines |

## Fuente de precios

Los precios se obtienen de la página de **Nous Portal**
(`https://portal.nousresearch.com/`), capturada como markdown (el portal bloquea
`curl` directo; se usa un extractor web). La API de OpenRouter se consulta solo
para nombre/contexto, porque sus precios incluyen margen y no coinciden con los
que muestra el portal.

Actualización: regenerar `prices.json` con `fetch_prices.py portal.md` y subir
`index.html` + `prices.json` + `pin.php` al hosting.

## Configuración local (no versionada)

- `config.js` → `window.PIN_TOKEN = "<token>";`
- `config.php` → `$PIN_TOKEN = '<token>';`

Ambos deben contener el mismo token; `pin.php` lo exige en el header
`X-Pin-Token` para aceptar POST (protección anti-basura, no seguridad real:
la web es pública).

## Privacidad

No se versionan: tokens (`config.*`), script de despliegue con rutas del
hosting (`deploy.py`), estado de anclados (`pins.json`), snapshots de trabajo
(`prices_prev.json`, `portal.md`).
