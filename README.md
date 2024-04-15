# Pasos para la instalación del Sistema Invoice

# Cursos de respaldo

- [Curso de Python con Django de 0 a Máster | Español](https://youtube.com/playlist?list=PLxm9hnvxnn-j5ZDOgQS63UIBxQytPdCG7 "Curso de Python con Django de 0 a Máster | Español")
- [Curso de Deploy de un Proyecto Django en un VPS Ubuntu | Español](https://youtube.com/playlist?list=PLxm9hnvxnn-hFNSoNrWM0LalFnSv5oMas "Curso de Deploy de un Proyecto Django en un VPS Ubuntu | Español")
- [Curso de Python con Django Avanzado I | Español](https://www.youtube.com/playlist?list=PLxm9hnvxnn-gvB0h0sEWjAf74ge4tkTOO "Curso de Python con Django Avanzado I | Español")
- [Curso de Python con Django Avanzado II | Español](https://www.youtube.com/playlist?list=PLxm9hnvxnn-jL7Fqr-GL2iSPfgJ99BhEC "Curso de Python con Django Avanzado II | Español")

# Instaladores

| Nombre                   | Instalador                                                                                                                                                                                                                                           |
|:-------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------| 
| `Compilador`             | [Python3](https://www.python.org/downloads/release/python-396/ "Python3")                                                                                                                                                                            |
| `IDE de programación`    | [Visual Studio Code](https://code.visualstudio.com/ "Visual Studio Code"), [Sublime Text](https://www.sublimetext.com/ "Sublime Text"), [Pycharm](https://www.jetbrains.com/es-es/pycharm/download/#section=windows "Pycharm")                       |
| `Motor de base de datos` | [Sqlite Studio](https://github.com/pawelsalawa/sqlitestudio/releases "Sqlite Studio"), [PostgreSQL](https://www.enterprisedb.com/downloads/postgres-postgresql-downloads "PostgreSQL"), [MySQL](https://www.apachefriends.org/es/index.html "MySQL") |

# Pasos de instalación

##### 1) Descomprimir el proyecto en una carpeta de tu sistema operativo

##### 2) Instalar Java en su computador, esto es importante para poder firmar los comprobantes con la firma electrónica

Para windows:

```bash
https://www.java.com/es/download/
```

Para linux:

```bash
https://www.digitalocean.com/community/tutorials/how-to-install-java-with-apt-on-ubuntu-20-04-es
```

##### 3) Crear un entorno virtual para posteriormente instalar las librerias del proyecto

Para windows:

```bash
python3 -m venv venv 
```

Para linux:

```bash
virtualenv venv -ppython3 
```

##### 4) Instalar el complemento de [weasyprint](https://weasyprint.org/ "weasyprint")

Si estas usando Windows debe descargar el complemento de [GTK3 installer](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases "GTK3 installer"). En algunas ocaciones se debe colocar en las variables de entorno como primera para que funcione y se debe reiniciar el computador.

Si estas usando Linux debes instalar las [librerias](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#linux "librerias") correspondientes a la distribución que tenga instalado en su computador.

##### 5) Activar el entorno virtual de nuestro proyecto

Para windows:

```bash
cd venv\Scripts\activate.bat 
```

Para Linux:

```bash
source venv/bin/active
```

##### 6) Instalar todas las librerias del proyecto que se encuentran en la carpeta deploy

```bash
pip install -r deploy/txt/requirements.txt
```

##### 7) Crear la tablas de la base de datos a partir de las migraciones

```bash
python manage.py makemigrations
python manage.py migrate
```

##### 8) Insertar datos en las entidades de los modulos de seguridad y usuario del sistema

```bash
python manage.py start_installation
```

##### 9) Insertar datos iniciales de categorías, productos, clientes, compras y ventas (Paso opcional)

```bash
python manage.py insert_test_data
```

##### 10) Iniciar el servidor del proyecto

```bash
python manage.py runserver 
```

Si deseas verlo en toda tu red puedes ejecutarlo asi:

```bash
python manage.py runserver 0:8000 o python manage.py runserver 0.0.0.0:8000
```

##### 11) Iniciar sesión en el sistema (Puede cambiar la clave y usuario que se crea en el archivo core/management/commands/start_installation.py del paso 8)

```bash
username: admin
password: hacker94
```

#### Si estas usando Linux, puedes ejecutar el bash de instalación que hara todos los pasos de instalación

```bash
bash deploy/sh/install.sh
```

# Pasos para la creación del cron de envió de comprobantes electrónicos

##### 1) Tener instalado cron en tu servidor de linux

```bash
sudo apt install cron
```

##### 2) Crear una nueva tarea en tu cron

```bash
crontab -e
```

##### 3) Crear la tarea de envio de correos en el cron, la palabra user hace referencia al usuario de tu server

```bash
*/1 * * * * bash /home/user/invoice/deploy/sh/electronic_billing.sh
```

##### 4) Reiniciar el servicio del cron en el servidor

```bash
sudo /etc/init.d/cron restart
```

------------

# Gracias por adquirir mi producto ✅🙏

#### Esto me sirve mucho para seguir produciendo mi contenido 🤗​

### ¡Apóyame! para seguir haciéndolo siempre 😊👏

Paso la mayor parte de mi tiempo creando contenido y ayudando a futuros programadores sobre el desarrollo web con tecnología open source.

🤗💪¡Muchas Gracias!💪🤗

**Puedes apoyarme de la siguiente manera.**

**Suscribiéndote**
https://www.youtube.com/c/AlgoriSoft?sub_confirmation=1

**Siguiendo**
https://www.facebook.com/algorisoft

**Donando por PayPal**
williamjair94@hotmail.com

***AlgoriSoft te desea lo mejor en tu aprendizaje y crecimiento profesional como programador 🤓.***

