"""Cotizacion de la lista de compras en todas las cadenas.

Responsabilidad unica: dado un conjunto de items y de cadenas, buscar cada item
en cada cadena, acordar con que envase se compara y armar una
`CotizacionCadena` por cadena.

El trabajo va en dos pasadas separadas a proposito:

1. `buscar` sale a la red y junta los candidatos crudos de las cinco cadenas.
2. `armar` no toca la red: acuerda el formato y elige un producto por cadena.

Estan separadas porque el usuario puede querer cambiar el envase con el que se
compara ("mostrame la Coca de 2,25 L, no la de 220 ml") y eso no deberia
significar volver a consultar cinco sitios.

Las busquedas van en paralelo porque son independientes, pero con un tope por
cadena: golpear un mismo sitio con diez pedidos simultaneos es la forma mas
rapida de que empiece a responder 429.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests

from nucleo import formato as formatos
from nucleo.coincidencias import elegir_mejor, unidades_necesarias
from nucleo.formato import Formato
from nucleo.modelos import CotizacionCadena, ItemLista, LineaCotizada, Oferta
from precios import registro
from precios.base import ErrorCadena, nueva_sesion

LOGGER = logging.getLogger(__name__)

# Pedidos simultaneos permitidos contra una misma cadena.
SIMULTANEAS_POR_CADENA = 3

# Pedidos simultaneos totales, sumando todas las cadenas.
SIMULTANEAS_TOTALES = 10


@dataclass
class Resultado:
    """Todo lo que produjo una corrida, incluido el material para rehacerla.

    `candidatos` guarda los productos crudos de cada cadena para cada item, de
    modo que cambiar el formato elegido sea un recalculo local y no una nueva
    ronda de consultas.
    """

    items: list[ItemLista]
    cadenas: list[str]
    candidatos: dict[tuple[str, int], list[Oferta]] = field(default_factory=dict)
    formatos: list[Formato] = field(default_factory=list)
    cotizaciones: dict[str, CotizacionCadena] = field(default_factory=dict)
    errores: dict[str, str] = field(default_factory=dict)

    def opciones_de_formato(self, indice: int) -> list[Formato]:
        """Envases que ofrecen las cadenas para ese item, del mas comun al menos."""
        if indice >= len(self.items):
            return []
        return formatos.opciones_ordenadas(self.items[indice], self.por_cadena(indice))

    def por_cadena(self, indice: int) -> dict[str, list[Oferta]]:
        """Candidatos de cada cadena para un item, agrupados."""
        return {
            cadena: list(self.candidatos.get((cadena, indice)) or [])
            for cadena in self.cadenas
        }


def cotizar(
    items: list[ItemLista],
    cadenas: list[str],
    *,
    sucursal_coto: str | None = None,
    sesion: requests.Session | None = None,
    al_avanzar: Callable[[int, int], None] | None = None,
) -> Resultado:
    """Consulta las cadenas y arma la cotizacion con el formato consensuado."""
    candidatos, errores = buscar(
        items,
        cadenas,
        sucursal_coto=sucursal_coto,
        sesion=sesion,
        al_avanzar=al_avanzar,
    )
    resultado = Resultado(
        items=list(items),
        cadenas=list(cadenas),
        candidatos=candidatos,
        errores=errores,
    )
    elegidos = [
        formatos.consensuar(item, resultado.por_cadena(indice))
        for indice, item in enumerate(items)
    ]
    return armar(resultado, elegidos)


def armar(resultado: Resultado, elegidos: list[Formato]) -> Resultado:
    """Elige un producto por cadena para cada item. No toca la red.

    Se puede volver a llamar con otros formatos para rehacer la comparacion con
    el envase que prefiera el usuario.
    """
    resultado.formatos = list(elegidos)
    resultado.cotizaciones = {
        clave: CotizacionCadena(cadena=clave) for clave in resultado.cadenas
    }

    for clave in resultado.cadenas:
        cotizacion = resultado.cotizaciones[clave]
        for indice, item in enumerate(resultado.items):
            envase = (
                elegidos[indice] if indice < len(elegidos) else formatos.FORMATO_LIBRE
            )
            candidatos = resultado.candidatos.get((clave, indice))
            if candidatos is None:
                # La busqueda de este item fallo en esta cadena. Es distinto de
                # haber buscado y no encontrar nada.
                cotizacion.lineas.append(LineaCotizada(item=item, oferta=None))
                continue
            mejor, alternativas = elegir_mejor(item, candidatos, formato=envase)
            cotizacion.lineas.append(
                LineaCotizada(
                    item=item,
                    oferta=mejor,
                    alternativas=alternativas,
                    envases=unidades_necesarias(envase, mejor) if mejor else 1,
                )
            )
        if clave in resultado.errores:
            cotizacion.error = resultado.errores[clave]

    return resultado


def buscar(
    items: list[ItemLista],
    cadenas: list[str],
    *,
    sucursal_coto: str | None = None,
    sesion: requests.Session | None = None,
    al_avanzar: Callable[[int, int], None] | None = None,
) -> tuple[dict[tuple[str, int], list[Oferta]], dict[str, str]]:
    """Trae los candidatos crudos de cada cadena para cada item.

    Devuelve (candidatos, errores). Un item que fallo en una cadena queda sin
    entrada en `candidatos`, para poder distinguirlo de uno que si se busco y
    no dio resultados.

    `al_avanzar` se llama con (hechas, totales) despues de cada busqueda, para
    que la interfaz pueda mostrar progreso.
    """
    candidatos: dict[tuple[str, int], list[Oferta]] = {}
    fallos: dict[str, list[str]] = {}
    if not items or not cadenas:
        return candidatos, {}

    propia = sesion is None
    sesion = sesion or nueva_sesion()

    # Un semaforo por cadena limita la concurrencia contra cada sitio sin
    # serializar el conjunto.
    cupos = {clave: threading.Semaphore(SIMULTANEAS_POR_CADENA) for clave in cadenas}
    total = len(items) * len(cadenas)
    hechas = 0
    candado = threading.Lock()

    def trabajo(clave: str, item: ItemLista) -> list[Oferta]:
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
                ejecutor.submit(trabajo, clave, item): (clave, indice)
                for clave in cadenas
                for indice, item in enumerate(items)
            }
            for futuro in as_completed(futuros):
                clave, indice = futuros[futuro]
                try:
                    candidatos[(clave, indice)] = futuro.result()
                except ErrorCadena as exc:
                    fallos.setdefault(clave, []).append(exc.mensaje)
                except Exception as exc:  # noqa: BLE001 - un item roto no frena la corrida
                    LOGGER.exception("fallo buscando en %s", clave)
                    fallos.setdefault(clave, []).append(
                        f"error inesperado ({exc.__class__.__name__})"
                    )
                with candado:
                    hechas += 1
                    if al_avanzar:
                        al_avanzar(hechas, total)
    finally:
        if propia:
            sesion.close()

    # Se informa un solo mensaje por cadena: repetir el mismo error una vez por
    # item no agrega informacion.
    errores = {
        clave: f"{mensajes[0]} ({len(mensajes)} de {len(items)} busquedas)"
        for clave, mensajes in fallos.items()
    }
    return candidatos, errores
