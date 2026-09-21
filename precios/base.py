"""Infraestructura HTTP compartida por los clientes de precios y promociones.

Responsabilidad unica: una sesion con reintentos, cabeceras crebles y un tope
de concurrencia, para no golpear los sitios mas fuerte de lo necesario.

Las cadenas no publican limites de tasa. Los valores de aca son deliberadamente
conservadores: la app consulta pocas veces y prefiere tardar un segundo mas
antes que hacerse bloquear.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)

TIEMPO_ESPERA = 20  # segundos por request
MAX_HILOS = 6  # busquedas simultaneas por cadena

_AGENTE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class ErrorCadena(RuntimeError):
    """Fallo al consultar una cadena. El mensaje es apto para mostrar en la UI."""

    def __init__(self, cadena: str, mensaje: str):
        super().__init__(f"{cadena}: {mensaje}")
        self.cadena = cadena
        self.mensaje = mensaje


def nueva_sesion() -> requests.Session:
    """Sesion con reintentos ante fallos transitorios y cabeceras de navegador."""
    sesion = requests.Session()
    politica = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adaptador = HTTPAdapter(max_retries=politica, pool_connections=12, pool_maxsize=12)
    sesion.mount("https://", adaptador)
    sesion.mount("http://", adaptador)
    sesion.headers.update(
        {
            "User-Agent": _AGENTE,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-AR,es;q=0.9",
        }
    )
    return sesion


def pedir_json(
    sesion: requests.Session,
    url: str,
    *,
    cadena: str,
    cabeceras: dict[str, str] | None = None,
    parametros: dict[str, Any] | None = None,
) -> Any:
    """GET que devuelve JSON o levanta ErrorCadena con un mensaje entendible."""
    try:
        respuesta = sesion.get(
            url, params=parametros, headers=cabeceras, timeout=TIEMPO_ESPERA
        )
    except requests.Timeout as exc:
        raise ErrorCadena(cadena, "la web no respondio a tiempo") from exc
    except requests.RequestException as exc:
        raise ErrorCadena(cadena, f"no se pudo conectar ({exc.__class__.__name__})") from exc

    # VTEX responde 206 Partial Content en las busquedas paginadas: es exito.
    if respuesta.status_code not in (200, 206):
        raise ErrorCadena(cadena, f"respondio HTTP {respuesta.status_code}")

    try:
        return respuesta.json()
    except ValueError as exc:
        raise ErrorCadena(cadena, "devolvio una respuesta que no es JSON") from exc
