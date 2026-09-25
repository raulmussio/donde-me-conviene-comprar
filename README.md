# Donde me conviene comprar

Compara una lista de compras en **Carrefour, Coto, Jumbo, Dia y ChangoMas** con
los precios que esas cadenas publican en ese momento, y le aplica las
**promociones bancarias** vigentes de cada una para decir donde conviene comprar
hoy y que dia de la semana conviene mas.

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Como se usa

Un paso por pantalla, en el orden en que se toman las decisiones:

1. **Productos.** Un menu por categorias, como una gondola: se tocan para
   agregarlos y la lista se arma al costado con su cantidad. Lo que no este se
   escribe a mano.
2. **Supermercados.** Contra cuales comparar, y si vas a comprar en sucursal o
   por la web.
3. **Medios de pago.** Tus bancos y billeteras, que es lo que habilita los
   descuentos.
4. **Marcas y envases.** Recien aca se consultan los precios, y se muestra que
   quedo elegido en cada producto **antes** de ver los totales, para poder
   corregirlo.
5. **Resultados.** El ranking de las cadenas, el detalle producto por producto,
   el calendario de los proximos siete dias y las promociones vigentes.

Las categorias no salen de una sola cadena sino del cruce de los arboles que
publican las cuatro que corren sobre VTEX. Cada una arma el suyo distinto:
Carrefour separa "Desayuno y merienda" de "Almacen", Dia los junta, Jumbo llama
"Frescos" a lo que otra llama "Lacteos y productos frescos". Quedarse con una
sola dejaba rubros enteros afuera.

Lo que se guarda en `nucleo/catalogo.py` no son productos concretos sino **lo
que se busca**: "leche entera", no "Leche Entera La Serenisima 1 L".

---

## Que hace

1. Lee tu lista de compras, armada desde el menu o escrita a mano.
2. Busca cada producto en las cinco cadenas, en paralelo.
3. Acuerda un envase comun a todas las cadenas y, si fijaste una marca, la
   respeta; con eso elige en cada cadena el producto que corresponde.
4. Suma el total de la canasta por cadena.
5. Aplica la mejor promocion bancaria disponible segun los bancos y billeteras
   que le digas que tenes.
6. Ordena las cadenas por lo que terminarias pagando, y proyecta los proximos
   siete dias para mostrarte si conviene esperar.

---

## De donde salen los datos

Ninguna de estas fuentes requiere clave privada ni login: son los mismos
endpoints publicos que consulta el navegador de cualquier visitante del sitio.

### Precios

| Cadena | Fuente | Formato |
|---|---|---|
| Carrefour | `www.carrefour.com.ar/api/catalog_system/pub/products/search` | VTEX |
| Jumbo | `www.jumbo.com.ar/api/catalog_system/pub/products/search` | VTEX |
| Dia | `diaonline.supermercadosdia.com.ar/api/catalog_system/...` | VTEX |
| ChangoMas | `www.masonline.com.ar/api/catalog_system/...` | VTEX |
| Coto | `ac.cnstrc.com/search/<termino>` | Constructor.io |

Coto no corre sobre VTEX: su tienda es una SPA que busca contra Constructor.io
con una clave publica embebida en su propio bundle `main.*.js`. Esa clave esta
en `precios/coto.py` como `CLAVE_BUSCADOR`. **Es el unico punto fragil del
cliente de precios**: si Coto la rota, hay que volver a leerla de esa pagina.

### Promociones bancarias

| Cadena | Fuente | Formato |
|---|---|---|
| Carrefour | `api/dataentities/BP/search` | VTEX Master Data |
| ChangoMas | `api/dataentities/BP/search` | VTEX Master Data (mismo esquema) |
| Jumbo | `api/dataentities/JN/documents/bankDiscount` | documento JSON unico |
| Coto | `rest/model/atg/actors/cProfileActor/getPromocionesMulticanal` | ATG |
| Dia | bloques de CMS incrustados en el HTML de su pagina de promociones | HTML |

Las cuatro primeras son datos estructurados con un campo por dia de la semana,
porcentaje, vigencia y letra chica. **Dia es la unica que no expone una API**:
sus promociones viajan serializadas dentro del HTML de la pagina. Si Dia cambia
la maquetacion, `promociones/dia.py` devuelve una lista vacia y la app avisa que
le falta esa fuente, en vez de romperse.

### Detalles de las APIs que costaron descubrir

Estan documentados en el codigo, pero conviene tenerlos a mano:

- **El WAF de Carrefour rechaza los espacios codificados como `+`.** Hay que
  mandar `%20`. Si se deja que `requests` arme la query string, responde
  `400 Bad Request! Scripts are not allowed!`. Ver `precios/vtex.py`.
- **La entidad `BP` responde 403 con `_fields=_all`** (`Cannot read private
  fields`): hay que enumerar los campos publicos uno por uno. Ver
  `promociones/vtex_bp.py`.
- **En Jumbo, `discount` es solo un numero y `discountText` es su sufijo.** El
  valor `12` con sufijo `"Cuotas sin interes"` son doce cuotas, no un 12% de
  descuento. Ver `_interpretar_descuento` en `promociones/jumbo.py`.
- **Coto devuelve un precio por cada sucursal**, no un precio unico. Ver
  `_precio_de_sucursal` en `precios/coto.py`.
- **Pasar `regionId` como parametro de la busqueda VTEX no hace nada.** El
  endpoint lo acepta y lo ignora: devuelve los mismos precios para CABA que para
  Cordoba. La zona se aplica con la cookie `vtex_segment`. Ver `precios/vtex.py`.

---

## Las ocho decisiones que definen si la app dice la verdad

### 1. No cotizar el producto equivocado

Los buscadores de las cadenas son generosos: pedir `leche` en Carrefour devuelve
`Pepitas artesanales dulce de leche` en el primer puesto. Comparar eso contra la
leche de otra cadena no es comparar precios.

`nucleo/coincidencias.py` vuelve a puntuar cada candidato por cuenta propia y
descarta lo que no llega al umbral. Si ninguna opcion convence, la app dice
**"no lo encontre en esta cadena"** en vez de cotizar cualquier cosa, y muestra
cuantos items le faltaron a cada cadena.

### 2. No dejarse enganar por fichas viejas

Los catalogos arrastran productos dados de baja que conservan el precio de hace
anios. Hoy conviven en Coto un arroz de 1 kg a $1.770 y otro, de nombre casi
identico, a $78,90. Tomar el segundo como "el precio de Coto" no seria encontrar
una oferta: seria un error.

`descartar_atipicos` corta contra la mediana de los propios candidatos, no
contra un monto fijo, para que el criterio siga sirviendo cuando los precios
cambien.

**Corre recien sobre los productos ya elegidos como comparables**, nunca sobre
la busqueda cruda. Aplicarlo antes comparaba cosas que no se comparan y borraba
justo lo correcto: buscando "leche" en ChangoMas los candidatos son chocolates
por gramo, cremas por mililitro y un extractor de leche de $241.999 por unidad;
contra esa mediana la unica leche de verdad, a $2.889 el litro, parecia un
precio imposible. Lo mismo con "banana": la fruta a $2.499 el kilo contra
galletitas de banana a $22.500 el kilo.

### 3. Comparar el costo de cubrir lo que pediste, no el precio de la etiqueta

Si pedis 1 kg y una cadena solo vende paquetes de 500 g, hacen falta dos. Sin
ese ajuste gana siempre la cadena que vende el formato mas chico, que es justo
al reves de lo que conviene. La columna **Envases** del detalle muestra cuantos
se contaron.

### 4. Comparar el mismo envase en todas las cadenas

Cuando no escribis el tamano, cada cadena elegia el suyo y la comparacion dejaba
de significar algo. Pedir `coca cola` traia una botella de 220 ml en Carrefour,
una de 600 ml en Coto y una de 354 ml en ChangoMas, y ganaba el envase mas
chico, no el mejor precio. Pedir `queso crema` traia un paquete de Cheetos de
43 gramos compitiendo contra potes de 290.

`nucleo/formato.py` acuerda primero **un solo envase para todas las cadenas**.
Recien despues se comparan precios dentro de ese envase. Eso tambien resuelve el
caso de los Cheetos sin necesidad de entender que son un snack: no entran en el
formato de 500 g que tienen cuatro de las cinco cadenas.

El envase elegido es el **comun**, no el mas chico ni el mas grande. Gana el que
esta en mas cadenas y, entre esos, el que tiene mas productos que son de verdad
lo que se pidio:

- La cobertura sola no alcanza porque se satura: con varios tamanos presentes en
  las cinco cadenas hay que desempatar, y hacerlo por calidad media elegia mal,
  porque esa media baja cuanto mas grande es el grupo. Para "queso crema" elegia
  el de 500 g, con 29 productos, sobre el de 290 g, que tiene 82 y es el que
  esta en toda gondola.
- Contar todos los productos tampoco alcanza, porque premia a los tamanos donde
  se juntan las variedades raras: para "azucar" elegia el sobre de 250 g, que
  suma 32 productos entre edulcorantes, azucar impalpable y azucar negra, sobre
  el paquete de 1 kg, que es el que se compra.

Contando solo los productos representativos, el formato elegido coincide con el
de gondola en los doce productos con los que se probo: azucar 1 kg, queso crema
290 g, detergente 500 ml, aceite 900 ml, fideos 500 g, yerba 500 g, papel
higienico 4 unidades, rollo de cocina 3 unidades.

El acuerdo es una prediccion, y puede no ser la que queres. Por eso la pestana
**Detalle por producto** tiene un selector de envase por item: cambiarlo rehace
la comparacion al instante, sin volver a consultar los sitios.

El filtro por formato es una preferencia, no una condicion excluyente. Si pedis
1 kg y una cadena solo vende paquetes de 500 g, se sigue ofreciendo esa cadena
con dos paquetes en vez de declarar que no tiene el producto.

### 5. Comparar cadenas que no tienen la misma lista

Es muy dificil que un supermercado tenga los veintiseis productos de tu lista, y
los totales crudos no son comparables entre si: a la cadena que no tiene dos de
ellos le falta el precio de esos dos, asi que suma menos sin ser mas barata.

El primer intento fue sumarle lo que costaria conseguirlos en otro lado, con el
precio tipico de las demas. Salio mal por dos motivos. El numero que se mostraba
dejaba de ser lo que se paga en la caja, y podia ser cualquier cosa: con dos
productos faltantes llegaba a sumar $49.824 de plata que nadie iba a gastar ahi.
Y sobre todo respondia una pregunta que nadie se hace: nadie reparte una compra
entre cinco supermercados. Se va al que mas conviene y lo que falte se ve
despues.

Ahora el orden lo decide un **indice de precios**: para cada producto que
cotizaron al menos dos cadenas se toma el precio tipico, y el indice de una
cadena es el promedio de cuanto se aparta de ese tipico. Un 0,90 quiere decir
que, producto por producto, sale un 10% menos que la media. Una cadena a la que
le faltan productos simplemente tiene menos terminos en ese promedio, no un
total mas chico.

El total que se muestra vuelve a ser plata real: lo que sale llevarte de ahi lo
que esa cadena si tiene.

La cobertura no se ignora, pero tampoco manda: una cadena que tiene bastante
menos de la lista compite recien despues de las que la cubren, por barata que
sea en lo poco que tiene.

### 6. La marca la elegis vos, y fijarla es excluyente

El envase se acuerda solo porque casi siempre hay una respuesta razonable. La
marca no: que la app elija por su cuenta entre Casancrem y la segunda marca de
cada cadena seria inventar una preferencia que nadie declaro. Por eso, sin
indicacion, no se fija ninguna y se compara por precio.

Cuando si la fijas, el filtro es **excluyente**, al reves que el de envase. Si
pediste Casancrem y una cadena no lo tiene, la respuesta correcta es que no lo
tiene: cotizarle otra marca seria contestar una pregunta que no hiciste. Esa
cadena queda con el item faltante y entra el mecanismo de la decision 5.

El selector muestra en cuantas cadenas existe cada marca, porque eso define que
tan completa va a ser la comparacion:

```
Casancrem  (5)     ->  comparacion entre las cinco
La Paulina (5)     ->  idem
Arla       (1)     ->  solo dice cuanto sale en Jumbo
```

Las cinco cadenas publican la marca en un campo propio y lo llenan bien, pero
cada una la escribe a su manera (`TREGAR`, `Tregar`, `LA PAULINA`,
`La Paulina`). `nucleo/marca.py` las agrupa por su forma normalizada y muestra
la grafia mas legible. Tambien mira el nombre del producto, para las fichas
donde el campo de marca quedo vacio o mal cargado.

Fijar una marca cambia los envases disponibles: los de Casancrem no son los de
La Paulina. Si el envase elegido antes deja de existir, se vuelve a acordar solo.

### 7. Lo que pediste tiene que ser el producto, no un ingrediente

Una busqueda de una o dos palabras la cumple cualquier producto que las
contenga. Pedir "leche" en ChangoMas devuelve arroz con leche, crema de leche,
alfajores de dulce de leche, un batidor de leche y un extractor de leche: con
solo contar palabras, los seis puntuan igual que la leche.

La senal que los separa es **donde** aparece la palabra. En las gondolas el tipo
de producto encabeza el nombre y lo que sigue lo especifica: "Leche Ilolay
Proteina 1 L" es leche, "Chocolate con leche Bariloche" no. `nucleo/coincidencias.py`
puntua esa posicion.

Ademas, solo compiten entre si los candidatos que estan a menos de un margen del
mejor puntaje de esa cadena. Sin eso, cualquier producto que apenas superara el
umbral ganaba por ser el mas barato.

### 8. Sin marca elegida, el mas barato de verdad

Cuando no fijas marca, la app cotiza el producto mas barato de cada cadena. Eso
ya lo hacia, pero elegia entre muy poco: los buscadores devuelven sus resultados
por relevancia propia, y con doce resultados buscar "leche" en Carrefour traia
solo dos leches de 1 L. La mas barata salia $3.119 cuando en la gondola habia
una a $1.890.

Se piden 30 resultados por busqueda. Con eso Carrefour pasa de dos leches a
ocho, y la mas barata baja a $1.890. Pasar a 50 ya no cambia el resultado.

Pedir el catalogo **ordenado por precio** parece el atajo obvio y es peor: llena
los primeros puestos con sachets y golosinas y deja cero leches de 1 L.

Ampliar la red trae mas candidatos malos, asi que hizo falta una regla mas. Hay
palabras que cambian lo que el producto es, y la diferencia es de significado y
no de escritura: "Detergente Lavavajillas Zorro" y "Detergente Ropa Ecovita"
comparten la palabra buscada, la tienen al principio y arrastran la misma
cantidad de palabras ajenas. Ninguna senal de texto los separa; lo que los separa
es que uno lava platos y el otro lava ropa. `MODIFICADORES_EXCLUYENTES` en
`nucleo/texto.py` los lista, y dejan de excluir si el pedido los nombra: quien
escribe "leche chocolatada" quiere exactamente eso.

En esa lista tambien esta **retornable**, por otro motivo: el precio de una
botella retornable no incluye el envase, asi que ponerlo a competir contra una
descartable es comparar dos numeros que no miden lo mismo.

Y estan las formas de nombrar la version sin azucar. "Coca-Cola Zero" tiene un
nombre mas corto que "Gaseosa Coca-Cola Sabor Original", asi que arrastra menos
palabras ajenas y puntuaba mas alto: las cinco cadenas terminaban cotizando la
Zero para quien pedia una Coca comun. Como la misma variante viene escrita como
"Zero", como "sin azucares" o como "menos azucares", hay tambien una lista de
**frases** excluyentes: "azucar" sola no sirve como senal, porque es el nombre
de un producto.

### Ademas: los supermercados no conocen sinonimos

En Argentina el papel de cocina se llama **rollo** de cocina. Pedir "papel de
cocina" devuelve un solo resultado en Carrefour y ninguno en ChangoMas; pedir
"rollo de cocina" devuelve doce en cada una. Cambiar la palabra es de lejos lo
que mas mejora los resultados, mucho mas que afinar la puntuacion.

`nucleo/texto.py` tiene las equivalencias de vocabulario y, cuando una cadena
responde con muy poco, `motor/canasta.py` reintenta con la otra forma de
nombrarlo y junta los dos conjuntos. El reintento solo ocurre cuando hizo falta.

### Ademas: lo fresco no declara envase

Una banana no dice cuanto pesa: se vende "x Kg" o "x Un". Como el acuerdo de
formato solo miraba los envases declarados, para "alcaucil" terminaba comparando
corazones de alcaucil en frasco a $18.890 cuando lo que se pidio vale $4.999 en
la verduleria.

Se resolvio de dos formas. "X Kg" y "Por Kg" se leen como **1 kg**, que es lo que
hace comparables entre si a los frescos: las cadenas publican la misma banana
como "Banana x Kg" o como "Banana 1 Kg", y leerlos distinto las dejaba en grupos
separados. Y lo que sigue sin envase compite como un formato mas, "fresco, por
unidad o peso", en vez de quedar afuera del acuerdo.

### Ademas: tamanos imposibles

Los catalogos tambien tienen errores de tipeo en las unidades. Coto publica hoy
`Coca-Cola Sabor Liviano 1,75 Ml` para una botella de 1,75 litros. Leerlo al pie
de la letra metia un envase de dos mililitros entre las opciones. `nucleo/texto.py`
descarta las medidas fuera del rango plausible de un envase de supermercado.

---

## Zonas: CABA y Gran Buenos Aires

El precio del mismo producto cambia segun donde compres, y cada cadena resuelve
la zona de una forma distinta. `precios/zonas.py` traduce "compro en zona sur" a
lo que cada una necesita.

| Cadena | Como se le pide la zona |
|---|---|
| Carrefour, Dia, ChangoMas | cookie `vtex_segment` con el `regionId` que devuelve su API de regiones para un codigo postal |
| Coto | no regionaliza la busqueda: devuelve el precio de **todas** sus sucursales en la misma respuesta, y la zona se aplica al recibir |
| Jumbo | no expone ninguna forma publica; se informa el precio de su tienda online |

**La zona no se elige desde la app.** Se consulta siempre la de CABA, porque
preguntarla no compensaba: dentro del area metropolitana casi no mueve el
precio. Se sigue usando internamente porque evita que a Coto se le cuele el
precio de una sucursal del interior. Las cuatro zonas siguen definidas en
`precios/zonas.py` por si se quiere volver a exponer.

### Cuanto cambia realmente

Medido sobre la misma busqueda y comparando por EAN:

- **Carrefour y Dia**: cotizan igual en CABA y en todo el GBA. Recien cambian
  entre provincias.
- **ChangoMas**: CABA y GBA Norte comparten lista; **GBA Oeste y GBA Sur
  difieren**. La misma leche Las Tres Ninas de 1 L vale $2.749 en CABA y $2.719
  en zona sur, y en el sur aparecen marcas que en CABA no estan.
- **Jumbo**: sus canales de venta responden `sc is inactive` y su API de
  regiones devuelve un error. No hay zona que pedir.

Por eso las cadenas que no publican precios por zona lo dicen en su propia
tarjeta: con "GBA Sur" elegido arriba, nadie supondria que una de las cinco esta
mostrando otra cosa.

### Que mas hace la zona

El precio es lo que menos cambia. Lo que la zona aporta de verdad es:

- **Donde ir.** La pestana *Sucursales de tu zona* lista los locales de cada
  cadena con nombre y direccion. Salen de `pickup-points` para las cadenas VTEX
  y del listado publico de Coto.
- **Si lo vas a conseguir.** El stock cambia por zona, asi que un producto que
  la cadena vende pero que en tu zona figura agotado se informa como
  **"lo vende, pero sin stock en tu zona"**, que no es lo mismo que "no
  encontrado". Sin esa distincion, una cadena parecia no tener un producto que
  si vende.

### Las sucursales de Coto se leen, no se escriben

El listado sale de `coto.com.ar/sucursales/index.asp`, que es una pagina plana
con las 122 sucursales, su numero, direccion y zona. Se lee al vuelo para que
abrir o cerrar una sucursal no obligue a tocar el codigo. Si la pagina falla,
Coto cotiza sin filtro de zona en vez de romperse.

Dentro de la zona se toma el precio **mas frecuente** entre sus sucursales, no
el minimo: el minimo suele ser una sucursal suelta con una promocion puntual, y
tomarlo haria parecer a Coto sistematicamente mas barato de lo que es.

---

## Como se aplican las promociones

- **Solo una promo por cadena.** Las promociones bancarias de supermercado no se
  acumulan: se paga con un medio y se obtiene un beneficio. La app elige la que
  mas ahorra, y la pantalla lo respeta: muestra una tarjeta por cadena y deja el
  resto en un desplegable. Listarlas todas sugiere que se suman, y ademas repite
  la misma linea cuando lo unico que cambia es el banco.
- **Gana la que mas ahorra, no la del porcentaje mas alto.** Un 30% con tope de
  $10.000 ahorra menos que un 15% sin tope en una compra de $120.000.
- **MODO no es un banco.** Una promo de "40% con Credicoop a traves de MODO"
  exige la tarjeta de Credicoop; tener la app instalada no alcanza. La app solo
  la da por cumplida cuando MODO es lo unico que la promo nombra. Ver
  `tiene_medio` en `motor/decision.py`.
- **Sucursal y web tienen promos distintas.** El selector "Como vas a comprar"
  filtra las que no aplican.

---

## Limitaciones conocidas

- **Jumbo no tiene zona.** Las otras cuatro cotizan la zona elegida; Jumbo
  informa el precio de su tienda online porque es el unico que publica. Su
  tarjeta lo aclara.
- **La zona es del area metropolitana.** Estan CABA y las tres zonas del GBA.
  Para el interior hay que agregar la zona a `precios/zonas.py` con su codigo
  postal y su etiqueta de Coto.
- **Los precios son los de la tienda online.** Pueden no coincidir exactamente
  con la gondola del local.
- **El banco se deduce del texto de la promo.** Ninguna cadena publica el
  emisor en un campo normalizado utilizable: Carrefour y Coto usan ids internos
  sin catalogo publico. El vocabulario esta en `promociones/bancos.py` y una
  promo con un emisor no listado queda sin entidad asignada. Esas promos se
  ocultan por defecto y se pueden mostrar con la casilla
  "Incluir promos sin banco identificado".
- **El calendario proyecta promociones, no precios.** Usa los precios de hoy
  para los siete dias. Las promos bancarias son semanales y conocidas de
  antemano; los precios no.
- **La app no compra ni reserva nada.** Solo informa.

---

## Compartirlo con otros

La app corre entera en el servidor, asi que alcanza con una URL: quien la abre
no instala nada. Se despliega gratis en **Streamlit Community Cloud**, que lee
el codigo de un repositorio de GitHub.

1. Creá un repositorio vacío en github.com (sin README ni .gitignore, para que
   no choque con el historial que ya existe).
2. Desde la carpeta del proyecto:

   ```bash
   git remote add origin https://github.com/USUARIO/REPO.git
   git push -u origin main
   ```

3. Entra a [share.streamlit.io](https://share.streamlit.io), iniciá sesión con
   GitHub y elegí **New app**. Repositorio, rama `main`, archivo `app.py`.
   En *Advanced settings* elegí **Python 3.11 o superior**: el codigo usa
   anotaciones que no existen antes de 3.10.
4. Sale una URL del estilo `tu-app.streamlit.app` para pasar por donde sea.

### Lo que conviene saber antes de difundirla

- **Cada visita consulta las cinco cadenas en vivo**, desde la IP compartida del
  servidor. Entre amigos no es problema. Si la app circula mucho, esa IP puede
  terminar limitada o bloqueada por alguna cadena, y ahi deja de traer precios.
- El cache juega a favor: es del proceso, no de cada visitante, asi que varias
  personas mirando lo mismo en la misma franja comparten las consultas. Los
  precios se reusan quince minutos y las promociones una hora.
- **No guarda nada de nadie.** No hay base de datos, ni cuentas, ni registro de
  las listas: todo vive en la sesion del navegador y se pierde al cerrarla.
- Las fuentes son endpoints publicos de cada cadena, los mismos que consulta el
  navegador de cualquier visitante de sus sitios. Aun asi, publicar una
  herramienta que los consulta de forma automatica es mas visible que usarla uno
  mismo: si alguna cadena bloquea el acceso, lo que corresponde es sacarla de la
  lista y no buscarle la vuelta.

---

## Estructura

```
app.py                    interfaz Streamlit; solo presentacion
nucleo/
  modelos.py              tipos que viajan entre capas
  texto.py                normalizacion y lectura de envases
  lista.py                parseo de la lista de compras
  coincidencias.py        puntuacion producto-pedido, atipicos, costo efectivo
  formato.py              acuerdo del envase comun entre cadenas
  marca.py                reconocimiento y fijado de marcas
precios/
  base.py                 sesion HTTP con reintentos y limites
  vtex.py                 Carrefour, Jumbo, Dia, ChangoMas
  coto.py                 Constructor.io
  registro.py             que cadena se consulta con que cliente
  zonas.py                CABA y GBA: regiones, sucursales y disponibilidad
promociones/
  bancos.py               vocabulario de entidades, topes y porcentajes
  vtex_bp.py              Carrefour y ChangoMas
  jumbo.py                Jumbo
  dia.py                  Dia
  coto.py                 Coto
  agregador.py            las cinco en paralelo, tolerante a fallos
motor/
  canasta.py              busca candidatos y arma la cotizacion (dos pasadas)
  decision.py             aplica promos, rankea y arma el calendario
ui/
  tema.py                 paleta y CSS
```

Las dependencias van en una sola direccion: `app` depende de `motor`, `motor` de
`precios` y `promociones`, y todos de `nucleo`. `nucleo` no depende de nada.
