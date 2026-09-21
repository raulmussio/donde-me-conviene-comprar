"""Cliente de precios para Coto Digital.

Responsabilidad unica: hablar con el buscador Constructor.io que usa Coto y
devolver objetos `Oferta`.

Coto no corre sobre VTEX: su tienda es una SPA que consulta `ac.cnstrc.com` con
una clave publica embebida en el bundle de la pagina. Esa clave es la misma que
usa el navegador de cualquier visitante.

La particularidad importante es que Coto devuelve un precio por cada sucursal en
la misma respuesta. No hay un "precio de Coto": hay decenas. Eso significa que
la zona no se pide, se aplica al recibir, quedandose con las sucursales que
corresponden. Ver `_precio_de_sucursal`.
"""

from __future__ import annotations

import logging
from collections import Counter

import requests

from nucleo.modelos import Oferta
from nucleo.texto import parsear_envase
from precios.base import ErrorCadena, pedir_json

LOGGER = logging.getLogger(__name__)

BASE = "https://ac.cnstrc.com/search"

# Clave publica del buscador, tal como la sirve www.coto.com.ar en su bundle
# `main.*.js`. Si Coto rota la clave, esta constante deja de funcionar y hay que
# volver a leerla de esa pagina: es el unico punto fragil del cliente.
CLAVE_BUSCADOR = "key_r6xzz4IAoTWcipni"

VERSION_CLIENTE = "ciojs-client-2.35.0"
RESULTADOS_POR_BUSQUEDA = 12


def buscar(
    sesion: requests.Session,
    *,
    consulta: str,
    sucursales: frozenset[str] | None = None,
    limite: int = RESULTADOS_POR_BUSQUEDA,
) -> list[Oferta]:
    """Busca `consulta` en Coto y devuelve las ofertas encontradas.

    `sucursales` son los numeros de las sucursales de la zona elegida. Si viene
    vacio se consideran todas.
    """
    parametros = {
        "key": CLAVE_BUSCADOR,
        "i": "00000000-0000-0000-0000-000000000001",
        "s": "1",
        "c": VERSION_CLIENTE,
        "num_results_per_page": str(limite),
        "page": "1",
    }
    url = f"{BASE}/{requests.utils.quote(consulta)}"
    crudo = pedir_json(sesion, url, cadena="coto", parametros=parametros)

    resultados = ((crudo or {}).get("response") or {}).get("results")
    if resultados is None:
        raise ErrorCadena("coto", "el buscador devolvio un formato inesperado")

    ofertas: list[Oferta] = []
    for resultado in resultados:
        oferta = _a_oferta(resultado, sucursales=sucursales)
        if oferta:
            ofertas.append(oferta)
    return ofertas


def _a_oferta(resultado: dict, *, sucursales: frozenset[str] | None) -> Oferta | None:
    """Convierte un resultado de Constructor.io en Oferta."""
    datos = resultado.get("data") or {}
    nombre = (resultado.get("value") or "").strip()
    if not nombre:
        return None

    precio = _precio_de_sucursal(datos.get("price"), sucursales=sucursales)
    if precio is None:
        # Respaldo: algunos resultados traen el precio plano en vez de la lista
        # por sucursal.
        plano = datos.get("product_list_price")
        precio = float(plano) if isinstance(plano, (int, float)) and plano > 0 else None
    if precio is None:
        return None

    magnitud, unidad = parsear_envase(nombre)
    if magnitud is None:
        # Coto publica el formato aparte ("1 L", "900 GR"); se usa si el nombre
        # no lo dice.
        formato = datos.get("product_format")
        cantidad = datos.get("product_format_quantity")
        if formato:
            magnitud, unidad = parsear_envase(f"{cantidad or ''} {formato}")

    identificador = datos.get("id") or resultado.get("value")

    return Oferta(
        cadena="coto",
        nombre=nombre,
        marca=(datos.get("product_brand") or "").strip() or None,
        precio=precio,
        precio_lista=None,
        ean=(str(datos.get("product_main_ean") or "").strip() or None),
        url=f"https://www.coto.com.ar/productos/{identificador}" if identificador else None,
        imagen=datos.get("image_url") or datos.get("product_medium_image_url"),
        disponible=True,
        magnitud=magnitud,
        unidad=unidad,
    )


def _precio_de_sucursal(
    precios: object, *, sucursales: frozenset[str] | None
) -> float | None:
    """Elige un precio entre los que Coto publica por sucursal.

    Con una zona elegida se miran solo sus sucursales. Entre ellas se toma el
    precio *mas frecuente*, no el minimo: el minimo suele ser una sucursal
    suelta con una promocion puntual, y tomarlo haria que Coto parezca
    sistematicamente mas barato de lo que es.

    Si ninguna sucursal de la zona cotiza el producto, se vuelve a considerar
    todas. Es preferible informar el precio general que declarar que Coto no
    tiene algo que si vende.
    """
    if not isinstance(precios, list) or not precios:
        return None

    validos: list[tuple[str, float]] = []
    for entrada in precios:
        if not isinstance(entrada, dict):
            continue
        valor = entrada.get("listPrice")
        if not isinstance(valor, (int, float)) or valor <= 0:
            continue
        validos.append((str(entrada.get("store") or "").zfill(3), float(valor)))

    if not validos:
        return None

    if sucursales:
        de_la_zona = [par for par in validos if par[0] in sucursales]
        if de_la_zona:
            validos = de_la_zona

    frecuencias = Counter(valor for _, valor in validos)
    return frecuencias.most_common(1)[0][0]
