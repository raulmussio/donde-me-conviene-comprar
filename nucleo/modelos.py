"""Tipos de datos compartidos por toda la aplicacion.

Responsabilidad unica: definir la forma de los datos que viajan entre capas.
No hace red, no calcula precios y no dibuja nada.

El flujo es siempre el mismo:

    ItemLista  ->  Oferta (una por cadena)  ->  CotizacionCadena  ->  Veredicto

`Promo` vive en paralelo: se resuelve por separado y se aplica al final,
sobre el total de cada cadena.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# Las cinco cadenas que compara la app. El orden es el de presentacion.
CADENAS = ("carrefour", "coto", "jumbo", "dia", "changomas")

NOMBRE_CADENA = {
    "carrefour": "Carrefour",
    "coto": "Coto",
    "jumbo": "Jumbo",
    "dia": "Dia",
    "changomas": "ChangoMas",
}


@dataclass(frozen=True)
class ItemLista:
    """Una linea de la lista de compras, tal como la escribio el usuario.

    `texto` es la consulta cruda ("leche descremada 1L"). `cantidad` multiplica
    el precio unitario. `unidad_objetivo` y `magnitud_objetivo` salen de parsear
    el texto y sirven para preferir el envase correcto al comparar.
    """

    texto: str
    cantidad: int = 1
    magnitud_objetivo: float | None = None
    unidad_objetivo: str | None = None

    @property
    def etiqueta(self) -> str:
        return f"{self.cantidad}x {self.texto}" if self.cantidad > 1 else self.texto


@dataclass(frozen=True)
class Oferta:
    """Un producto concreto de una cadena, candidato a satisfacer un ItemLista."""

    cadena: str
    nombre: str
    marca: str | None
    precio: float
    precio_lista: float | None = None
    ean: str | None = None
    url: str | None = None
    imagen: str | None = None
    disponible: bool = True
    # Magnitud normalizada del envase: (900.0, "g") -> se usa para $/unidad.
    magnitud: float | None = None
    unidad: str | None = None
    # Puntaje de parecido con el ItemLista, 0..1. Lo asigna el matcher.
    puntaje: float = 0.0

    @property
    def precio_por_unidad(self) -> float | None:
        """Precio por litro o por kilo. None si no se pudo parsear el envase."""
        if not self.magnitud or self.magnitud <= 0:
            return None
        return self.precio / self.magnitud

    @property
    def en_oferta(self) -> bool:
        return bool(self.precio_lista and self.precio_lista > self.precio)


@dataclass
class LineaCotizada:
    """Resultado de buscar un ItemLista en una cadena puntual.

    `envases` es cuantas unidades del producto hacen falta para cubrir una vez
    lo pedido: si pediste 1 kg y la cadena solo vende paquetes de 500 g, son 2.
    """

    item: ItemLista
    oferta: Oferta | None
    alternativas: list[Oferta] = field(default_factory=list)
    envases: int = 1
    # Por que no hay oferta elegida. "sin_stock" significa que la cadena si
    # vende el producto pero en la zona elegida figura agotado.
    motivo: str | None = None

    @property
    def encontrado(self) -> bool:
        return self.oferta is not None

    @property
    def unidades_totales(self) -> int:
        return self.item.cantidad * max(1, self.envases)

    @property
    def subtotal(self) -> float:
        return self.oferta.precio * self.unidades_totales if self.oferta else 0.0


@dataclass
class CotizacionCadena:
    """La lista completa cotizada en una cadena, antes de aplicar promociones."""

    cadena: str
    lineas: list[LineaCotizada] = field(default_factory=list)
    error: str | None = None

    @property
    def nombre(self) -> str:
        return NOMBRE_CADENA.get(self.cadena, self.cadena)

    @property
    def total(self) -> float:
        return sum(linea.subtotal for linea in self.lineas)

    @property
    def encontrados(self) -> int:
        return sum(1 for linea in self.lineas if linea.encontrado)

    @property
    def faltantes(self) -> list[str]:
        return [linea.item.texto for linea in self.lineas if not linea.encontrado]

    @property
    def cobertura(self) -> float:
        """Fraccion de la lista que la cadena pudo satisfacer, 0..1.

        Importa para el ranking: una cadena barata que solo tiene la mitad de la
        lista no es realmente mas barata.
        """
        if not self.lineas:
            return 0.0
        return self.encontrados / len(self.lineas)


@dataclass(frozen=True)
class Promo:
    """Una promocion bancaria normalizada, venga de donde venga.

    Cada cadena publica sus promos con un esquema distinto; los adaptadores de
    `promociones/` las traducen todas a esta forma para poder compararlas.

    `dias` son enteros al estilo `datetime.weekday()`: lunes=0 .. domingo=6.
    `porcentaje` es 20.0 para "20% de descuento"; None si la promo es solo
    cuotas sin interes (no reduce el total, por eso se informa aparte).
    """

    cadena: str
    titulo: str
    bancos: tuple[str, ...]
    porcentaje: float | None
    dias: frozenset[int]
    tope: float | None = None
    cuotas: int | None = None
    medio_pago: str | None = None
    requiere_modo: bool = False
    vigencia_desde: dt.date | None = None
    vigencia_hasta: dt.date | None = None
    solo_online: bool = False
    solo_sucursal: bool = False
    detalle: str | None = None
    legal: str | None = None

    def vigente_el(self, dia: dt.date) -> bool:
        """True si la promo corre ese dia: cae en el dia de semana y esta en fecha."""
        if dia.weekday() not in self.dias:
            return False
        if self.vigencia_desde and dia < self.vigencia_desde:
            return False
        if self.vigencia_hasta and dia > self.vigencia_hasta:
            return False
        return True

    def ahorro_sobre(self, total: float) -> float:
        """Cuanto descuenta esta promo sobre un total, respetando el tope."""
        if not self.porcentaje or total <= 0:
            return 0.0
        bruto = total * (self.porcentaje / 100.0)
        return min(bruto, self.tope) if self.tope else bruto


@dataclass
class Veredicto:
    """Una cadena ya evaluada con promo aplicada, lista para rankear.

    `estimado_afuera` es lo que costaria conseguir en otro lado los items que
    esta cadena no tiene, estimado con el precio tipico de las cadenas que si
    los tienen. Sin ese termino la comparacion es tramposa: una cadena a la que
    le falta un producto muestra un total mas bajo sin ser mas barata, y una que
    tiene todo puede quedar primera aunque cueste diez mil pesos mas.
    """

    cotizacion: CotizacionCadena
    promo: Promo | None
    ahorro: float
    estimado_afuera: float = 0.0
    faltantes: int = 0

    @property
    def cadena(self) -> str:
        return self.cotizacion.cadena

    @property
    def nombre(self) -> str:
        return self.cotizacion.nombre

    @property
    def total_bruto(self) -> float:
        return self.cotizacion.total

    @property
    def total_final(self) -> float:
        """Lo que pagas en esta cadena, ya con la promocion aplicada."""
        return max(0.0, self.total_bruto - self.ahorro)

    @property
    def total_canasta(self) -> float:
        """Lo que te sale la lista completa si comprar el grueso aca.

        Es el numero con el que se comparan las cadenas entre si, porque es el
        unico que representa la misma canasta en todas.
        """
        return self.total_final + self.estimado_afuera

    @property
    def es_estimado(self) -> bool:
        return self.faltantes > 0
