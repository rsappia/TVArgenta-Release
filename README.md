# TVArgenta---Retro-TV
TVArgenta es una TV retro hecha con Raspberry Pi que revive la experiencia de hacer zapping entre publicidades y contenido offline. Incluye un backend local para gestionar videos, canales y metadatos, todo dentro de una carcasa 3D impresa.

# Primera parte: Configuracion basica de la Raspberry Pi

Preparamos la tarjeta SD en este caso uso una de 64Gb. 
Para eso usamos Raspberry Pi Imager 
Asegurarse de elegir lo siguiente:

<img width="516" height="98" alt="GetImage(1)" src="https://github.com/user-attachments/assets/0e5f1ac6-0984-432c-be08-1437c1fbc2ae" />

En el hostname me aseguro de q poner argentv.local (lo vamos a usar mas adelante, pero pueden ponerle el hostname que quieran) 

<img width="516" height="98" alt="GetImage(1)" src="https://github.com/user-attachments/assets/ed7ae1b7-f9fa-4088-97f8-4d550d3298d6" />

Asegurarse de configurar las credenciales de conexion a WIFI, idioma y region. 
Dejar activado SSH para poder acceder luego a la raspberry en forma remota: 

<img width="532" height="341" alt="GetImage(2)" src="https://github.com/user-attachments/assets/2db92e9c-3a0c-4588-ae73-04a006b02310" />

Darle a instalar, nos vemos en unos minutos 😉 
[...]
Una vez que termina el proceso de flasheo, insertamos la tarjeta SD en la raspberry pi y si vemos lo siguiente vamos por buen camino: 
<img width="916" height="660" alt="GetImage(3)" src="https://github.com/user-attachments/assets/fb1c9e5d-ed64-4b4a-8d6a-49a96241ab09" />

<img width="893" height="584" alt="GetImage(4)" src="https://github.com/user-attachments/assets/27b006af-634a-4407-8305-b08e9cbbef18" />

A continuacion, vamos a intentar acceder a la raspberry en forma remota. Para eso abrimos la consola de comando y tipeamos lo siguiente: 

`ssh argentv.local`

Puede ser que el siguiente mensaje nos aparezca: 

<img width="688" height="245" alt="GetImage(5)" src="https://github.com/user-attachments/assets/b8f6b68c-e219-46e8-8b86-d9ac209fcbbd" />

Si llegara a suceder, probamos lo siguiente: 

`ssh-keygen -R argentv.local`

 <img width="551" height="113" alt="GetImage(6)" src="https://github.com/user-attachments/assets/79f8c030-8a48-4163-90bd-4815fb365669" />

Una vez hecho esto, volvemos a probar con ssh argentv.local y esta vez deberia mostrar lo siguiente: 

<img width="842" height="262" alt="GetImage(7)" src="https://github.com/user-attachments/assets/6aed27de-c5a3-4c33-9fc8-56bec1065421" />

Despues de escribir `yes` como opcion, se instalan los nuevos certificados y se establece la conexion con la raspberry pi via SSH.  

Mi usuario durante la instalacion lo puse como "rs", aca puede haber diferencia con el usuartio que hayan puesto ustedes, para tenrlo en cuenta el resto del setup. 

Como es el primer arranque de todos despues de formatear la SD ejecutamos los siguientes comandos: 

`sudo apt update && sudo apt upgrade –y ` 

Ahora pasamos a clonar el repo en github. Antes es necesario configurar nuestras claves para poder hacerlo. 


### 1) Si ya tenés claves, salteá este paso 

`ls -l ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub 2>/dev/null || true `

  

### 2) Generar una clave nueva (ED25519). Elegí un comentario útil: 

`ssh-keygen -t ed25519 -C "pi@argentv" ` 

Apretá Enter para aceptar la ruta por defecto (~/.ssh/id_ed25519) 

Podés dejar passphrase vacía (Enter) o poner una (más seguro) 

### 3) Mostrar la clave pública (esta sí se copia a GitHub) 

`cat ~/.ssh/id_ed25519.pub`

### 4) (Opcional) Cargarla en el agente para no poner passphrase cada vez 

`eval "$(ssh-agent -s)"`
`ssh-add ~/.ssh/id_ed25519` 

Copiá esa clave pública. 

Agregá la clave a tu GitHub 

Web: GitHub → tu avatar → Settings → SSH and GPG keys → New SSH key → pegá la clave. 
 

### 5) Probar conexión con GitHub (debería saludar con tu usuario) 

`ssh -T git@github.com`

Si todo sale bien debrias recibir un saludo con tu usuario como el siguiente: 

"Hi [user]! You've successfully authenticated, but GitHub does not provide shell access." 

A continuacion preparamos el directorio donde vamos a clonar el repo: 

Asegurate que /srv exista (ya existe) y dale ownership a tu usuario (nuevamente notar q mi usuario es rs pero deben usar el de ustedes) 

```
cd /srv 
git clone git@github.com:rsappia/TVArgenta---Retro-TV.git tvargenta 
cd /srv/tvargenta
```
 <img width="729" height="202" alt="GetImage(8)" src="https://github.com/user-attachments/assets/67f7129d-25c5-4643-bff6-c400c3e3e00e" />

##Instalar dependencias del sistema y del proyecto 
Ejecutamos:
```
sudo apt update 
sudo apt install -y ffmpeg python3 python3-venv python3-pip dos2unix git 
```
Luego vamos al siguiente dierectorio: 

`cd /srv/tvargenta/software `

Y ejecutamos: 
```
python3 -m venv venv  
source venv/bin/activate 
sudo apt update && sudo apt install -y python3 python3-pip && python3 -m pip install --upgrade pip && python3 -m pip install Flask 
```
Preparamos tambien lo necvesario para compilar el .c del encoder: 

`sudo apt install -y build-essential libgpiod-dev pkg-config` 

Cambiamos de directorio para compilar el .c del encoder 

`cd /srv/tvargenta/software/app/native`

Una vez ahi, largamos el compilador. 

`gcc encoder_reader.c -o encoder_reader $(pkg-config --cflags --libs libgpiod) `

Si sale todo bien, deberia apraecer ahora el .bin compilado junto con el .c 

 <img width="488" height="38" alt="GetImage(9)" src="https://github.com/user-attachments/assets/a3ee3968-8d51-42f3-9fc6-97d0212d373b" />

A continuacion ajustamos los permisos necesarios:  
```
chmod +x encoder_reader 
cd /srv/tvargenta/software 
chmod +x scripts/*.sh 
```
Ya a esta altura podemos hacer una primer prueba de largar la aplicacion y ver si todo esta bien. Para eso no posicionamos en el siguiente directorio: 


`cd /srv/tvargenta/software/app $ `
Y estano ahi, ejecutamos  
`python main.py `

Si todo va bien, deberia aparecer un video de intro y luego pasar a la reproduccion de canales, q de momento esta en default y sin nada cargado en el estado inicial. Es decir, vamos a estar viendo una pantalla "negra". 

Podemos probar de mover el encoder y pulsarlo para ver si sale el menu 

Vamos a agregar un par de videos para ver que todo este funcionando correctamente. 
Para eso, se pueden usar directamente los videos disponibles en : 
`/srv/tvargenta/software/app/assets/Splash/videos `

Estos viene por defecto en el repo de github.  

![TVArgenta first load](https://github.com/rsappia/TVArgenta---Retro-TV/blob/main/docs/TVArgenta_first_load.gif)

 
Whit this, you are already good to go an play around. I will be posting on the next chapter about audio configuration and on a third one all related to the hardware itself.


<hr>

<p align="center">
  <em>Si te trajo una sonrisa o te inspiró a crear algo propio,<br>
  convidame un cafecito y seguimos haciendo magia argenta ☕🇦🇷</em>
</p>

<p align="center">
  <a href="https://paypal.me/RicardoSappia/5" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" width="200">
  </a>
</p>


