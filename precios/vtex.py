"""Cliente de precios para las cadenas montadas sobre VTEX.

Responsabilidad unica: traducir la respuesta del catalogo publico de VTEX
(`/api/catalog_system/pub/products/search`) a objetos `Oferta`.

Sirve para Carrefour, Jumbo, Dia y ChangoMas, que comparten plataforma y por lo
tanto esquema. Lo unico que cambia entre ellas es el dominio y el canal de
venta, que definen que lista de precios se devuelve.
"""

from __future__ import annotations

import logging
import urllib.parse

import requests

from nucleo.modelos import Oferta
from nucleo.texto import parsear_envase
from precios.base import ErrorCadena, pedir_json

LOGGER = logging.getLogger(__name__)

# Cuantos productos pedir por busqueda. El buscador de VTEX ordena por
# relevancia propia, que no siempre coincide con la nuestra, asi que tomamos un
# puñado y volvemos a puntuar con `nucleo.coincidencias`.
RESULTADOS_POR_BUSQUEDA = 12


def buscar(
    sesion: requests.Session,
    *,
    cadena: str,
    dominio: str,
    consulta: str,
    canal_venta: str | None = None,
    limite: int = RESULTADOS_POR_BUSQUEDA,
) -> list[Oferta]:
    """Busca `consulta` en una tienda VTEX y devuelve las ofertas encontradas."""
    # El termino de busqueda va codificado a mano con %20. Si se deja que
    # `requests` arme la query, los espacios viajan como "+" y el WAF de
    # Carrefour responde 400 "Scripts are not allowed!". Las otras tres toleran
    # ambas formas, asi que se usa la que funciona en todas.
    termino = urllib.parse.quote(consulta.strip())
    url = (
        f"https://{dominio}/api/catalog_system/pub/products/search"
        f"?ft={termino}&_from=0&_to={max(0, limite - 1)}"
    )
    if canal_venta:
        url += f"&sc={urllib.parse.quote(canal_venta)}"

    crudo = pedir_json(sesion, url, cadena=cadena)
    if not isinstance(crudo, list):
        raise ErrorCadena(cadena, "el catalogo devolvio un formato inesperado")

    ofertas: list[Oferta] = []
    for producto in crudo:
        oferta = _a_oferta(producto, cadena=cadena, dominio=dominio)
        if oferta:
            ofertas.append(oferta)
    return ofertas


def _a_oferta(producto: dict, *, cadena: str, dominio: str) -> Oferta | None:
    """Convierte un producto de VTEX en Oferta. None si no es comprable."""
    articulos = producto.get("items") or []
    if not articulos:
        return None

    # Un producto VTEX agrupa SKUs (sabores, tamanos). Tomamos el mas barato
    # disponible: es el que el usuario veria como precio del producto.
    mejor_precio: float | None = None
    mejor_articulo: dict | None = None
    mejor_venta: dict | None = None

    for articulo in articulos:
        for vendedor in articulo.get("sellers") or []:
            venta = vendedor.get("commertialOffer") or {}
            precio = venta.get("Price")
            if not precio or precio <= 0:
                continue
            if not venta.get("IsAvailable", True):
                continue
            if venta.get("AvailableQuantity", 0) <= 0:
                continue
            if mejor_precio is None or precio < mejor_precio:
                mejor_precio, mejor_articulo, mejor_venta = precio, articulo, venta

    if mejor_precio is None or mejor_articulo is None or mejor_venta is None:
        return None

    nombre = producto.get("productName") or mejor_articulo.get("nameComplete") or ""
    if not nombre:
        return None

    # El envase se lee del nombre; si el SKU trae unidad de medida explicita y
    # el nombre no dice nada, se usa como respaldo.
    magnitud, unidad = parsear_envase(nombre)

    precio_lista = mejor_venta.get("ListPrice")
    if precio_lista is not None and precio_lista <= mejor_precio:
        precio_lista = None

    enlace = producto.get("link") or producto.get("linkText")
    if enlace and not str(enlace).startswith("http"):
        enlace = f"https://{dominio}/{urllib.parse.quote(str(enlace))}/p"

    imagenes = mejor_articulo.get("images") or []

    return Oferta(
        cadena=cadena,
        nombre=nombre.strip(),
        marca=(producto.get("brand") or "").strip() or None,
        precio=float(mejor_precio),
        precio_lista=float(precio_lista) if precio_lista else None,
        ean=(mejor_articulo.get("ean") or "").strip() or None,
        url=enlace,
        imagen=(imagenes[0].get("imageUrl") if imagenes else None),
        disponible=True,
        magnitud=magnitud,
        unidad=unidad,
    )
