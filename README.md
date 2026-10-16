\# Demo de Federated Byzantine Agreement (FBA) con implementación de Stellar-core



Red privada de validadores stellar-core en contenedores Docker, con un panel web para ver el estado de la red, editar los quorum slices y probar el comportamiento de la red ante distintas ocurrencias.



\## Requisitos



\- Docker

\- Python 3



\## Crear el entorno desde cero


<!-- cd fba-demo -->

<!-- docker compose down -v -->

<!-- cd .. -->

<!-- rmdir /s /q fba-demo -->

```

python fba_docker_demo.py

cd fba-demo

docker compose up -d

python fba_dashboard.py

```

(El panel qeb debería habrirse al ejecutar el script, de lo contrario se encuentra en: http://localhost:8080)



\## Usar el panel



\- \*\*Pulsa un nodo\*\* para ver y editar su quorum slice.

\- \*\*Parar / Arrancar\*\* cada nodo simula caídas.

\- \*\*Aplicar y reiniciar red\*\* reinicia todo con la topología editada (el ledger vuelve a empezar).

\- Los \*\*escenarios\*\* del editor cargan una red sana o un fork de dos grupos aislados.

\- La columna \*\*Hash\*\* y el banner rojo muestran si hay un fork.



\## Terminar



1\. En la ventana del panel: `Ctrl + C`.

2\. En `fba-demo`:

&#x20;  - `docker compose stop` para parar y conservar el estado

&#x20;  - `docker compose down -v --remove-orphans` para borrarlo todo


