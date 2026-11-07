# Radar de alta costura

Buscador público de empleos, consultorías y proyectos de alta costura y moda de autor. Prioriza Colombia y el trabajo remoto elegible desde Colombia. [Abrir el radar](https://farenassr.github.io/radar-alta-costura/).

## Funcionamiento

GitHub Actions consulta las fuentes a las 00:17, 06:17, 12:17 y 18:17, hora de Colombia, y publica el resultado en GitHub Pages. La búsqueda también se puede iniciar en **Actions → Actualizar radar → Run workflow**. Los horarios están sujetos a la cola de GitHub. La publicación utiliza servicios gratuitos y las fuentes públicas pueden actualizarse con su propia frecuencia.

El ranking suma afinidad con el sector (hasta 55), elegibilidad desde Colombia (25), actualidad (hasta 10) y claridad de postulación (10). Dentro de cada sección, se desempata por la fecha de publicación o actualización. Si falla una fuente, las ofertas anteriores sin vencer se conservan hasta 48 horas desde su última consulta exitosa, con una marca de verificación pendiente. El registro semanal de publicación permite encontrar la ejecución asociada.

## Uso local

Se requiere Python 3.11 o posterior y curl. Ejecutar desde la carpeta del proyecto.

~~~sh
python -m unittest discover -v
python radar.py
python -m http.server 8000 --directory site
~~~

Abrir [el servidor local](http://localhost:8000/) para consultar el resultado. Los datos generados viven en el sitio publicado y en el estado temporal de Actions. El repositorio contiene el código y las pruebas.
