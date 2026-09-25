"""Aplicacion de promociones y ranking de cadenas.

Responsabilidad unica: dado lo que cuesta la lista en cada cadena y que
promociones hay, decidir donde conviene comprar hoy y en los proximos dias.

La regla central es que las promociones bancarias de supermercado no se
acumulan: se paga con un medio de pago y se obtiene un beneficio. Por eso, para
cada cadena se elige la unica promo que mas ahorra, en vez de sumar todas las
que aplican.
"""

from __future__ import annotations

import datetime as dt
import logging
import statistics
from dataclasses import dataclass

from nucleo.modelos import CotizacionCadena, Promo, Veredicto
from promociones.bancos import CANALES

LOGGER = logging.getLogger(__name__)

# Horizonte del calendario de promociones.
DIAS_A_FUTURO = 7


@dataclass(frozen=True)
class Preferencias:
    """Que tiene el usuario y como piensa comprar."""

    entidades: frozenset[str] = frozenset()
    # "sucursal" o "online". Filtra las promos que no aplican a esa modalidad.
    modalidad: str = "sucursal"
    # Si es False, solo se consideran promos de los bancos elegidos.
    incluir_sin_banco: bool = False


def promos_aplicables(
    promos: list[Promo],
    *,
    cadena: str,
    dia: dt.date,
    preferencias: Preferencias,
) -> list[Promo]:
    """Promos de una cadena que corren ese dia para las tarjetas del usuario."""
    salida: list[Promo] = []
    for promo in promos:
        if promo.cadena != cadena:
            continue
        if not promo.vigente_el(dia):
            continue
        if preferencias.modalidad == "sucursal" and promo.solo_online:
            continue
        if preferencias.modalidad == "online" and promo.solo_sucursal:
            continue
        if not tiene_medio(promo, preferencias):
            continue
        salida.append(promo)
    return salida


def tiene_medio(promo: Promo, preferencias: Preferencias) -> bool:
    """True si el usuario puede pagar con lo que esta promo exige.

    MODO se descuenta de la exigencia cuando la promo nombra tambien a un
    emisor: "40% con Credicoop a traves de MODO" pide la tarjeta de Credicoop, y
    darla por cumplida porque el usuario tiene MODO instalado seria prometerle
    un descuento que en la caja no va a existir.

    Cuando MODO es lo unico que la promo nombra, si alcanza con tener la app y
    cualquier tarjeta cargada.
    """
    if not promo.bancos:
        # Promo sin entidad reconocida: puede ser de la tarjeta de la propia
        # cadena o un texto que no supimos leer. No se asume que el usuario la
        # tiene, salvo que lo pida expresamente.
        return preferencias.incluir_sin_banco

    if not preferencias.entidades:
        return False

    emisores = tuple(clave for clave in promo.bancos if clave not in CANALES)
    exigidos = emisores or promo.bancos
    return any(clave in preferencias.entidades for clave in exigidos)


def mejor_promo(
    promos: list[Promo],
    *,
    cadena: str,
    dia: dt.date,
    total: float,
    preferencias: Preferencias,
) -> tuple[Promo | None, float]:
    """La promo que mas ahorra sobre ese total, con el monto ahorrado.

    El tope de reintegro hace que el mejor porcentaje no siempre gane: un 30%
    con tope de $10.000 ahorra menos que un 15% sin tope en una compra de
    $120.000. Por eso se compara el ahorro y no el porcentaje.
    """
    candidatas = promos_aplicables(promos, cadena=cadena, dia=dia, preferencias=preferencias)
    mejor: Promo | None = None
    mejor_ahorro = 0.0
    for promo in candidatas:
        ahorro = promo.ahorro_sobre(total)
        if ahorro > mejor_ahorro:
            mejor, mejor_ahorro = promo, ahorro
    return mejor, mejor_ahorro


# Dos cadenas tienen que haber cotizado un producto para que su precio tipico
# signifique algo.
MINIMO_PARA_COMPARAR = 2

# Que fraccion de la mejor cobertura hay que alcanzar para competir de igual a
# igual. Una cadena que tiene bastante menos de tu lista puede ser la mas barata
# en lo que tiene y aun asi no servirte, porque te deja media compra sin hacer.
COBERTURA_MINIMA = 0.85


def indices_de_precio(
    cotizaciones: dict[str, CotizacionCadena],
) -> dict[str, tuple[float, int]]:
    """Cuanto cuesta cada cadena comparada con el precio tipico de cada producto.

    Devuelve, por cadena, (indice, sobre cuantos productos se calculo). Un 0,90
    quiere decir que producto por producto sale un 10% menos que la media.

    Es lo que permite comparar cadenas que no tienen la misma lista. Los totales
    crudos no sirven: a la que no tiene dos de tus productos le falta el precio
    de esos dos, asi que suma menos sin ser mas barata.
    """
    por_item: dict[int, list[float]] = {}
    for cotizacion in cotizaciones.values():
        for indice, linea in enumerate(cotizacion.lineas):
            if linea.encontrado:
                por_item.setdefault(indice, []).append(linea.subtotal)

    tipicos = {
        indice: statistics.median(valores)
        for indice, valores in por_item.items()
        if len(valores) >= MINIMO_PARA_COMPARAR and statistics.median(valores) > 0
    }

    salida: dict[str, tuple[float, int]] = {}
    for clave, cotizacion in cotizaciones.items():
        razones = [
            linea.subtotal / tipicos[indice]
            for indice, linea in enumerate(cotizacion.lineas)
            if linea.encontrado and indice in tipicos
        ]
        salida[clave] = (statistics.fmean(razones) if razones else 1.0, len(razones))
    return salida


def evaluar(
    cotizaciones: dict[str, CotizacionCadena],
    promos: list[Promo],
    *,
    dia: dt.date,
    preferencias: Preferencias,
) -> list[Veredicto]:
    """Aplica la mejor promo a cada cadena y las ordena de mas a menos conveniente.

    El orden lo decide el indice de precios, no el total: el total de una cadena
    a la que le faltan productos es mas bajo sin que sea mas barata, y sumarle lo
    que costaria conseguirlos en otro lado es inventar un gasto que nadie va a
    hacer ahi. Nadie reparte una compra entre cinco supermercados: se va al que
    mas conviene y lo que falte se ve despues.

    La cobertura no se ignora, pero tampoco manda: una cadena que tiene bastante
    menos de la lista compite recien despues de las que la cubren, por barata
    que sea en lo poco que tiene.
    """
    indices = indices_de_precio(cotizaciones)

    veredictos: list[Veredicto] = []
    for cotizacion in cotizaciones.values():
        if not cotizacion.lineas or cotizacion.encontrados == 0:
            continue
        promo, ahorro = mejor_promo(
            promos,
            cadena=cotizacion.cadena,
            dia=dia,
            total=cotizacion.total,
            preferencias=preferencias,
        )
        indice, comparables = indices.get(cotizacion.cadena, (1.0, 0))
        veredictos.append(
            Veredicto(
                cotizacion=cotizacion,
                promo=promo,
                ahorro=ahorro,
                # El descuento tambien abarata: se aplica al indice en la misma
                # proporcion en que baja el total.
                indice=indice * (1 - (ahorro / cotizacion.total if cotizacion.total else 0)),
                comparables=comparables,
            )
        )

    if not veredictos:
        return []

    mejor_cobertura = max(v.cotizacion.encontrados for v in veredictos)
    piso = mejor_cobertura * COBERTURA_MINIMA

    def orden(veredicto: Veredicto) -> tuple:
        cubre = 0 if veredicto.cotizacion.encontrados >= piso else 1
        return (cubre, veredicto.indice, -veredicto.cotizacion.encontrados)

    veredictos.sort(key=orden)
    return veredictos


@dataclass(frozen=True)
class DiaDelCalendario:
    """Como queda cada dia del horizonte: donde conviene y con que promo."""

    fecha: dt.date
    cadena: str | None
    nombre_cadena: str | None
    promo: Promo | None
    # Lo que se paga ese dia en la cadena elegida, ya con la promo aplicada.
    total: float
    # Precio relativo al tipico de cada producto: es lo que decide que cadena
    # gana ese dia, igual que en el ranking.
    indice: float
    ahorro: float

    @property
    def es_hoy(self) -> bool:
        return self.fecha == dt.date.today()


def calendario(
    cotizaciones: dict[str, CotizacionCadena],
    promos: list[Promo],
    *,
    desde: dt.date | None = None,
    dias: int = DIAS_A_FUTURO,
    preferencias: Preferencias,
) -> list[DiaDelCalendario]:
    """Proyecta el mejor destino de compra para cada uno de los proximos dias.

    Usa los precios de hoy para todos los dias: no predice precios, predice
    promociones. Es la unica parte de la app que mira al futuro, y lo hace
    porque las promos bancarias son semanales y conocidas de antemano.
    """
    desde = desde or dt.date.today()
    agenda: list[DiaDelCalendario] = []

    for desplazamiento in range(max(1, dias)):
        fecha = desde + dt.timedelta(days=desplazamiento)
        veredictos = evaluar(cotizaciones, promos, dia=fecha, preferencias=preferencias)
        if not veredictos:
            agenda.append(
                DiaDelCalendario(
                    fecha=fecha,
                    cadena=None,
                    nombre_cadena=None,
                    promo=None,
                    total=0.0,
                    indice=1.0,
                    ahorro=0.0,
                )
            )
            continue
        ganador = veredictos[0]
        agenda.append(
            DiaDelCalendario(
                fecha=fecha,
                cadena=ganador.cadena,
                nombre_cadena=ganador.nombre,
                promo=ganador.promo,
                total=ganador.total_final,
                indice=ganador.indice,
                ahorro=ganador.ahorro,
            )
        )
    return agenda
