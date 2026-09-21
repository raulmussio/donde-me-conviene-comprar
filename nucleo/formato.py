"""Acuerdo de un formato de envase comun entre las cinco cadenas.

Responsabilidad unica: decidir, para un item de la lista, que tamano de envase
se va a comparar en todas las cadenas.

Sin esta capa cada cadena elige su envase por su cuenta y la comparacion deja de
significar algo. Pedir "coca cola" devolvia una botella de 220 ml en Carrefour,
una de 600 ml en Coto y una de 354 ml en ChangoMas, y el "mas barato" terminaba
siendo el envase mas chico, no el mejor precio. Peor todavia: "queso crema"
traia un paquete de Cheetos de 43 gramos compitiendo contra potes de 290.

La regla es elegir el formato que **mas cadenas tienen**, y recien despues
comparar precios dentro de ese formato. Si el usuario escribio el tamano, manda
el usuario y no hay nada que acordar.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from nucleo.modelos import ItemLista, Oferta
from nucleo.texto import formatear_envase

LOGGER = logging.getLogger(__name__)

# Dos envases se consideran el mismo formato si sus tamanos no difieren mas que
# este factor. Cubre las diferencias reales entre marcas (900 ml contra 1 L,
# 480 g contra 500 g, 190 g contra 200 g) sin mezclar tamanos que el cliente ve
# como distintos: con 1.3 una Coca de 2,25 L entraba a competir contra las de
# 1,75 L de las otras cadenas, que es un 28% mas de producto por un precio que
# se mostraba como si fuera comparable.
TOLERANCIA = 1.2


@dataclass(frozen=True)
class Formato:
    """El tamano de envase con el que se compara un item en todas las cadenas."""

    magnitud: float | None
    unidad: str | None

    @property
    def es_libre(self) -> bool:
        """True cuando no se pudo acordar un tamano y vale cualquiera."""
        return not self.magnitud or not self.unidad

    @property
    def etiqueta(self) -> str:
        if self.es_libre:
            return "cualquier envase"
        return formatear_envase(self.magnitud, self.unidad)

    def contiene(self, oferta: Oferta) -> bool:
        """True si el envase de la oferta entra en este formato."""
        if self.es_libre:
            return True
        if not oferta.magnitud or oferta.unidad != self.unidad:
            return False
        mayor = max(oferta.magnitud, self.magnitud)
        menor = min(oferta.magnitud, self.magnitud)
        return mayor / menor <= TOLERANCIA


FORMATO_LIBRE = Formato(magnitud=None, unidad=None)


def del_item(item: ItemLista) -> Formato | None:
    """El formato que pidio el usuario, si escribio un tamano."""
    if item.magnitud_objetivo and item.unidad_objetivo:
        return Formato(magnitud=item.magnitud_objetivo, unidad=item.unidad_objetivo)
    return None


def consensuar(
    item: ItemLista, candidatos_por_cadena: dict[str, list[Oferta]]
) -> Formato:
    """Elige el formato con el que se va a comparar este item.

    Gana el tamano presente en mas cadenas. Entre empates decide la calidad
    media de las coincidencias, que es lo que separa tres potes de queso crema
    de 290 g de dos paquetes de Cheetos de 43 g: los Cheetos arrastran palabras
    ajenas al pedido y puntuan mas bajo.
    """
    pedido = del_item(item)
    if pedido:
        return pedido

    opciones = _opciones(candidatos_por_cadena)
    if not opciones:
        return FORMATO_LIBRE
    return opciones[0]


def opciones_ordenadas(
    item: ItemLista, candidatos_por_cadena: dict[str, list[Oferta]]
) -> list[Formato]:
    """Todos los formatos que ofrecen las cadenas, del mas comun al menos.

    Es lo que alimenta el selector de la interfaz para que el usuario pueda
    corregir el formato elegido sin volver a consultar los sitios.
    """
    opciones = _opciones(candidatos_por_cadena)
    pedido = del_item(item)
    if pedido and not any(_mismo(pedido, opcion) for opcion in opciones):
        opciones.insert(0, pedido)
    return opciones


def _opciones(candidatos_por_cadena: dict[str, list[Oferta]]) -> list[Formato]:
    """Formatos candidatos, ordenados por cuantas cadenas los tienen."""
    con_envase = [
        (cadena, oferta)
        for cadena, ofertas in candidatos_por_cadena.items()
        for oferta in ofertas
        if oferta.magnitud and oferta.unidad
    ]
    if not con_envase:
        return []

    # Cada tamano distinto es un formato candidato. Se agrupan los equivalentes
    # dentro de la tolerancia para no tratar 900 ml y 1 L como dos mundos.
    vistos: list[Formato] = []
    for _, oferta in con_envase:
        propuesto = Formato(magnitud=oferta.magnitud, unidad=oferta.unidad)
        if not any(_mismo(propuesto, existente) for existente in vistos):
            vistos.append(propuesto)

    puntuados: list[tuple[float, int, float, Formato]] = []
    for formato in vistos:
        cadenas: set[str] = set()
        puntajes: list[float] = []
        for cadena, oferta in con_envase:
            if formato.contiene(oferta):
                cadenas.add(cadena)
                puntajes.append(oferta.puntaje)
        if not cadenas:
            continue
        calidad = sum(puntajes) / len(puntajes) if puntajes else 0.0
        # Orden: mas cadenas primero; a igualdad, mejor calidad de coincidencia;
        # y recien ahi el envase mas grande, que suele ser el formato familiar.
        puntuados.append((-len(cadenas), -round(calidad, 3), -(formato.magnitud or 0), formato))

    puntuados.sort(key=lambda fila: fila[:3])
    return [fila[3] for fila in puntuados]


def _mismo(uno: Formato, otro: Formato) -> bool:
    """True si dos formatos son el mismo tamano dentro de la tolerancia."""
    if uno.unidad != otro.unidad:
        return False
    if not uno.magnitud or not otro.magnitud:
        return uno.magnitud == otro.magnitud
    mayor = max(uno.magnitud, otro.magnitud)
    menor = min(uno.magnitud, otro.magnitud)
    return mayor / menor <= TOLERANCIA


def agrupar_por_cadena(
    candidatos: dict[tuple[str, int], list[Oferta]], indice: int, cadenas: list[str]
) -> dict[str, list[Oferta]]:
    """Reordena los candidatos crudos a un diccionario por cadena, para un item."""
    salida: dict[str, list[Oferta]] = defaultdict(list)
    for cadena in cadenas:
        salida[cadena] = list(candidatos.get((cadena, indice)) or [])
    return dict(salida)
