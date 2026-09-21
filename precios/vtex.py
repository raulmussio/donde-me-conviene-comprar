"""Cliente de precios para las cadenas montadas sobre VTEX.

Responsabilidad unica: traducir la respuesta del catalogo publico de VTEX
(`/api/catalog_system/pub/products/search`) a objetos `Oferta`.

Sirve para Carrefour, Jumbo, Dia y ChangoMas, que comparten plataforma y por lo
tanto esquema.

La zona se aplica con la cookie `vtex_segment`, que lleva el `regionId` de la
zona. Es el mecanismo que usa el propio sitio y es el que funciona:

- Pasar `regionId` como parametro de la busqueda **no sirve**: el endpoint lo
  acepta y lo ignora en silencio, devolviendo los mismos precios para CABA que
  para Cordoba. Es la clase de detalle que hace creer que la zona anda cuando no.
- El buscador moderno (`intelligent-search`) si respeta `regionId`, pero filtra
  por stock de envio a domicilio y deja afuera la mayoria de los productos: para
  "leche entera 1 l" en Carrefour devuelve 3 productos contra los 12 del
  catalogo clasico, y varios de los que descarta tienen precio de gondola
  perfectamente valido. Para comparar precios de super eso es peor, no mejor.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse

import requests

from nucleo.modelos import Oferta
from nucleo.texto import parsear_envase
from precios.base import ErrorCadena, pedir_json

LOGGER = logging.getLogger(__name__)

# Cuantos productos pedir por busqueda. El buscador de VTEX ordena por
# relevancia propia, que no siempre coincide con la nuestra, asi que tomamos un
# grupo grande y volvemos a puntuar con `nucleo.coincidencias`.
#
# Son 30 y no 12 porque de eso depende que "el mas barato" sea de verdad el mas
# barato. Con 12, buscar "leche" en Carrefour traia solo dos leches de 1 L y la
# mas barata salia $3.119; con 30 trae ocho y la mas barata sale $1.890. Pasar a
# 50 ya no cambia el resultado.
#
# Pedir el catalogo ordenado por precio (`O=OrderByPriceASC`) parece el atajo
# obvio y es peor: llena los primeros puestos con sachets y golosinas y deja
# cero leches de 1 L.
RESULTADOS_POR_BUSQUEDA = 30


def buscar(
    sesion: requests.Session,
    *,
    cadena: str,
    dominio: str,
    consulta: str,
    region_id: str | None = None,
    canal_venta: str | None = None,
    limite: int = RESULTADOS_POR_BUSQUEDA,
) -> list[Oferta]:
    """Busca `consulta` en una tienda VTEX y devuelve las ofertas encontradas.

    Con `region_id` los precios son los de esa zona; sin el, los de la lista por
    defecto de la tienda.
    """
    url = (
        f"https://{dominio}/api/catalog_system/pub/products/search"
        f"?ft={_termino(consulta)}&_from=0&_to={max(0, limite - 1)}"
    )
    if canal_venta:
        url += f"&sc={urllib.parse.quote(canal_venta)}"

    crudo = pedir_json(sesion, url, cadena=cadena, cabeceras=_cabeceras(region_id))
    if not isinstance(crudo, list):
        raise ErrorCadena(cadena, "el catalogo devolvio un formato inesperado")

    ofertas: list[Oferta] = []
    for producto in crudo:
        oferta = _a_oferta(producto, cadena=cadena, dominio=dominio)
        if oferta:
            ofertas.append(oferta)
    return ofertas


def _termino(consulta: str) -> str:
    """Codifica el termino de busqueda con %20 en vez de "+".

    Si se deja que `requests` arme la query, los espacios viajan como "+" y el
    WAF de Carrefour responde 400 "Scripts are not allowed!". Las otras tres
    toleran ambas formas, asi que se usa la que funciona en todas.
    """
    return urllib.parse.quote(consulta.strip())


def _cabeceras(region_id: str | None) -> dict[str, str] | None:
    """Cookie de segmento que le dice a VTEX desde que zona se consulta."""
    if not region_id:
        return None
    segmento = base64.b64encode(
        json.dumps({"regionId": region_id, "channel": "1"}).encode()
    ).decode()
    return {"Cookie": f"vtex_segment={segmento}"}


def _a_oferta(producto: dict, *, cadena: str, dominio: str) -> Oferta | None:
    """Convierte un producto de VTEX en Oferta. None si no es comprable."""
    articulos = producto.get("items") or []
    if not articulos:
        return None

    # Un producto VTEX agrupa SKUs (sabores, tamanos). Tomamos el mas barato
    # disponible: es el que el usuario veria como precio del producto.
    # Se busca el mas barato con stock. Si no hay ninguno con stock se conserva
    # el mas barato sin el, marcado como no disponible: con una zona elegida no
    # es lo mismo "esta cadena no lo vende" que "en tu zona esta sin stock", y
    # callarlo hace parecer que la app no encontro el producto.
    mejor_precio: float | None = None
    mejor_articulo: dict | None = None
    mejor_venta: dict | None = None
    hay_stock = False

    for articulo in articulos:
        for vendedor in articulo.get("sellers") or []:
            venta = vendedor.get("commertialOffer") or {}
            precio = venta.get("Price")
            if not precio or precio <= 0:
                continue
            con_stock = bool(
                venta.get("IsAvailable", True) and venta.get("AvailableQuantity", 0) > 0
            )
            # Una oferta con stock siempre le gana a una sin stock, por barata
            # que sea la segunda.
            if con_stock and not hay_stock:
                mejor_precio, mejor_articulo, mejor_venta, hay_stock = (
                    precio,
                    articulo,
                    venta,
                    True,
                )
            elif con_stock == hay_stock and (mejor_precio is None or precio < mejor_precio):
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
        disponible=hay_stock,
        magnitud=magnitud,
        unidad=unidad,
    )
