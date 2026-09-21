"""Cotizacion de la lista de compras en todas las cadenas.

Responsabilidad unica: dado un conjunto de items y de cadenas, buscar cada item
en cada cadena, elegir el producto que corresponde y armar una
`CotizacionCadena` por cadena.

Las busquedas van en paralelo porque son independientes, pero con un tope por
cadena: golpear un mismo sitio con diez pedidos simultaneos es la forma mas
rapida de que empiece a responder 429.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from nucleo.coincidencias import elegir_mejor, unidades_necesarias
from nucleo.modelos import CotizacionCadena, ItemLista, LineaCotizada, Oferta
from precios import registro
from precios.base import ErrorCadena, nueva_sesion

LOGGER = logging.getLogger(__name__)

# Pedidos simultaneos permitidos contra una misma cadena.
SIMULTANEAS_POR_CADENA = 3

# Pedidos simultaneos totales, sumando todas las cadenas.
SIMULTANEAS_TOTALES = 10


def cotizar(
    items: list[ItemLista],
    cadenas: list[str],
    *,
    sucursal_coto: str | None = None,
    sesion: requests.Session | None = None,
    al_avanzar: Callable[[int, int], None] | None = None,
) -> dict[str, CotizacionCadena]:
    """Cotiza la lista en cada cadena pedida.

    `al_avanzar` se llama con (hechas, totales) despues de cada busqueda, para
    que la UI pueda mostrar progreso.
    """
    cotizaciones = {clave: CotizacionCadena(cadena=clave) for clave in cadenas}
    if not items or not cadenas:
        return cotizaciones

    propia = sesion is None
    sesion = sesion or nueva_sesion()

    # Un semaforo por cadena limita la concurrencia contra cada sitio sin
    # serializar el conjunto.
    cupos = {clave: threading.Semaphore(SIMULTANEAS_POR_CADENA) for clave in cadenas}
    resultados: dict[tuple[str, int], list[Oferta] | ErrorCadena] = {}
    total = len(items) * len(cadenas)
    hechas = 0
    candado = threading.Lock()

    def trabajo(clave: str, indice: int, item: ItemLista):
        with cupos[clave]:
            return registro.buscar(
                sesion,
                clave_cadena=clave,
                consulta=item.texto,
                sucursal_coto=sucursal_coto,
            )

    try:
        with ThreadPoolExecutor(max_workers=SIMULTANEAS_TOTALES) as ejecutor:
            futuros = {
                ejecutor.submit(trabajo, clave, indice, item): (clave, indice)
                for clave in cadenas
                for indice, item in enumerate(items)
            }
            for futuro in as_completed(futuros):
                clave, indice = futuros[futuro]
                try:
                    resultados[(clave, indice)] = futuro.result()
                except ErrorCadena as exc:
                    resultados[(clave, indice)] = exc
                except Exception as exc:  # noqa: BLE001 - un item roto no frena la corrida
                    LOGGER.exception("fallo buscando en %s", clave)
                    resultados[(clave, indice)] = ErrorCadena(
                        clave, f"error inesperado ({exc.__class__.__name__})"
                    )
                with candado:
                    hechas += 1
                    if al_avanzar:
                        al_avanzar(hechas, total)
    finally:
        if propia:
            sesion.close()

    for clave in cadenas:
        cotizacion = cotizaciones[clave]
        errores: list[str] = []
        for indice, item in enumerate(items):
            resultado = resultados.get((clave, indice))
            if isinstance(resultado, ErrorCadena):
                errores.append(resultado.mensaje)
                cotizacion.lineas.append(LineaCotizada(item=item, oferta=None))
                continue
            mejor, alternativas = elegir_mejor(item, resultado or [])
            cotizacion.lineas.append(
                LineaCotizada(
                    item=item,
                    oferta=mejor,
                    alternativas=alternativas,
                    envases=unidades_necesarias(item, mejor) if mejor else 1,
                )
            )
        if errores:
            # Se informa un solo mensaje por cadena: repetir el mismo error una
            # vez por item no agrega informacion.
            cotizacion.error = f"{errores[0]} ({len(errores)} de {len(items)} busquedas)"

    return cotizaciones
