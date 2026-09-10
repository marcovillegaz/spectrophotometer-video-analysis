# CONTEXTO
Estamos midiendo la absorbancia mediante un espectrofotometro y uan celda de flujo continuo. El espectrofotmetro no tiene el software. Por lo cual, como buenos ingenieros, grabamos la pantalla digital para obtener un video de la absorbancia en tiempo real. 

# INSTRUCCIONES
Desarrolla un software que permita extraer los valores numericos de la absorbancia en funcion del tiempo, para anlizarlos posteriormente con excel u otros scripts. 

pasos
- Extraer los fotogramas de los videos. Guardarlos en una carpeta dedicada. El nombre del archivo debe reflejar el tiempo del video. 
- FIltrar las imagenes que esten en buen estado, mediante un pipeline de procesomiento que permita eliminar aqwuellas iamgenes oscuras, de mala resolución, otros. 
- Luego, mediante un modelo, extraer el valor numerico en las imagenes, retornar un archivo csv con columnas abs vs tiempo. 

# CONDICIONES DE BORDE
USar python
usar un ambiente virtual
siempre pregutnar los supeustos